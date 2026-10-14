import Foundation

/// Persistent evidence-only queue. Never stores screenshots, OCR text or credentials.
/// Files are in the app-group container and use a bounded retention limit.
final class ScreenEvidenceQueue {
    private let folder: URL
    private let limit = 100

    init?() {
        guard let root = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "group.com.tetradim.sentinelcrier"
        ) else { return nil }
        folder = root.appendingPathComponent("screen-observations", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        } catch { return nil }
    }

    func pendingCount() -> Int {
        ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension == "json" }.count
    }

    func clear() {
        guard let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil) else { return }
        for file in files where file.pathExtension == "json" { try? FileManager.default.removeItem(at: file) }
    }

    func enqueue(_ evidence: ScreenEvidence) {
        guard let data = try? JSONEncoder().encode(evidence) else { return }
        let file = folder.appendingPathComponent(evidence.evidenceId + ".json")
        // Do not silently discard the oldest evidence during an outage.
        // Once full, retain existing receipts until they can be delivered.
        guard FileManager.default.fileExists(atPath: file.path) || pendingCount() < limit else { return }
        try? data.write(to: file, options: [.atomic, .completeFileProtectionUnlessOpen])
    }

    func flush() async {
        guard let (base, token) = ScreenUploadConfiguration.load() else { return }
        guard base.scheme?.lowercased() == "https", base.host != nil, base.user == nil, base.password == nil else { return }
        let endpoint = base.appendingPathComponent("api/screen-observations")
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: nil
        ) else { return }
        for file in files.filter({ $0.pathExtension == "json" }).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }).prefix(12) {
            guard let current = ScreenUploadConfiguration.load(),
                  current.0 == base, current.1 == token else { break }
            guard let data = try? Data(contentsOf: file) else { continue }
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.timeoutInterval = 8
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
            request.httpBody = data
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse else { break }
                if http.statusCode == 202 {
                    // Do not erase evidence if upload configuration changed mid-request.
                    if let current = ScreenUploadConfiguration.load(),
                       current.0 == base, current.1 == token {
                        try? FileManager.default.removeItem(at: file)
                    }
                } else if http.statusCode == 401 || http.statusCode == 403 ||
                          http.statusCode == 413 || http.statusCode == 422 {
                    // Bad credentials or evidence: stop; do not spin/retry aggressively.
                    break
                } else {
                    break
                }
            } catch { break }
        }
    }

}

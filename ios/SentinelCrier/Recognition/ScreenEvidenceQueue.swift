import Foundation

/// Persistent evidence-only queue. Never stores screenshots, OCR text or credentials.
/// Files are in the app-group container and use a bounded retention limit.
final class ScreenEvidenceQueue {
    private let folder: URL

    init?() {
        guard let root = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "group.com.tetradim.sentinelcrier"
        ) else { return nil }
        folder = root.appendingPathComponent("screen-observations", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        } catch { return nil }
    }

    func enqueue(_ evidence: ScreenEvidence) {
        guard let data = try? JSONEncoder().encode(evidence) else { return }
        let file = folder.appendingPathComponent(evidence.evidenceId + ".json")
        // Evidence UUID remains stable across retries.
        try? data.write(to: file, options: .atomic)
        prune()
    }

    func flush() async {
        guard let (base, token) = ScreenUploadConfiguration.load() else { return }
        guard base.scheme?.lowercased() == "https", base.host != nil, base.user == nil, base.password == nil else { return }
        let endpoint = base.appendingPathComponent("api/screen-observations")
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: nil
        ) else { return }
        for file in files.filter({ $0.pathExtension == "json" }).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }).prefix(12) {
            guard ScreenUploadConfiguration.load() != nil else { break }
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
                    try? FileManager.default.removeItem(at: file)
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

    private func prune() {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: [.contentModificationDateKey]
        ) else { return }
        // Bound on-device storage even during prolonged network outages.
        let sorted = files.filter { $0.pathExtension == "json" }.sorted {
            let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a > b
        }
        for file in sorted.dropFirst(100) { try? FileManager.default.removeItem(at: file) }
    }
}

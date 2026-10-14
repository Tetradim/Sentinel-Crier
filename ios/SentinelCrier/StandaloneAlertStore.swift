import Foundation

/// Durable, on-device observations. The broadcast extension is short-lived, so
/// network ambiguity is kept as "uncertain" rather than blindly resending.
final class StandaloneAlertStore {
    struct Record: Codable, Identifiable {
        var id: String { evidence.evidenceId }
        let evidence: ScreenEvidence
        var state: String
        var note: String
        var createdAt: Date
    }

    private let folder: URL
    private let maxRecords = 250

    init?() {
        guard let root = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: StandaloneConfiguration.group) else { return nil }
        folder = root.appendingPathComponent("standalone-alerts", isDirectory: true)
        do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true) }
        catch { return nil }
    }

    func records() -> [Record] {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: nil) else { return [] }
        return files.filter { $0.pathExtension == "json" }.compactMap {
            guard let data = try? Data(contentsOf: $0) else { return nil }
            return try? JSONDecoder().decode(Record.self, from: data)
        }.sorted { $0.createdAt > $1.createdAt }
    }

    private func write(_ record: Record) -> Bool {
        let url = folder.appendingPathComponent(record.id + ".json")
        guard let data = try? JSONEncoder().encode(record) else { return false }
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try data.write(to: url, options: [.atomic, .completeFileProtectionUnlessOpen])
            return true
        } catch {
            UserDefaults(suiteName: StandaloneConfiguration.group)?.set(
                Date().timeIntervalSince1970, forKey: "standaloneWriteFailureAt")
            return false
        }
    }

    func append(_ evidence: ScreenEvidence) {
        let existing = records()
        // Persisted fingerprints prevent repeated Discord alerts after a broadcast restart.
        // This intentionally favors missing a repeated identical trade over a false duplicate.
        let fingerprint = [evidence.broker, evidence.symbol, evidence.expiration,
                           evidence.right, evidence.strike, evidence.side,
                           String(evidence.quantity), evidence.fillPrice].joined(separator: "|")
        guard !existing.contains(where: {
            let e = $0.evidence
            return [e.broker, e.symbol, e.expiration, e.right, e.strike, e.side,
                    String(e.quantity), e.fillPrice].joined(separator: "|") == fingerprint
        }) else { return }
        if existing.count >= maxRecords {
            // Preserve unresolved evidence. Only discard oldest completed records.
            guard let oldest = existing.reversed().first(where: { $0.state == "sent" }) else { return }
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(oldest.id + ".json"))
        }
        _ = write(Record(evidence: evidence, state: "pending",
                         note: "Unverified screen observation", createdAt: Date()))
    }

    func sendPending() async {
        guard StandaloneConfiguration.enabled,
              let webhook = StandaloneConfiguration.webhook() else { return }
        for var record in records().reversed().filter({ $0.state == "pending" }).prefix(10) {
            guard StandaloneConfiguration.enabled,
                  StandaloneConfiguration.webhook() == webhook else { break }
            // Mark uncertain BEFORE the request. A crash or timeout must not duplicate a message.
            record.state = "uncertain"
            record.note = "Delivery may have occurred; do not automatically retry"
            guard write(record) else { break }
            let e = record.evidence
            let message = "⚠️ UNVERIFIED SCREEN OBSERVATION — NOT A BROKER-CONFIRMED FILL\n" +
                "\(e.broker) · \(e.symbol) \(e.expiration) \(e.strike)\(e.right) · " +
                "\(e.side) \(e.quantity) @ $\(e.fillPrice)\n" +
                "Observed via user-authorized iPhone screen OCR. Verify against broker records."
            var request = URLRequest(url: webhook)
            request.httpMethod = "POST"
            request.timeoutInterval = 10
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: [
                "content": message, "allowed_mentions": ["parse": []]
            ])
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse else { break }
                if (200..<300).contains(http.statusCode) {
                    record.state = "sent"
                    record.note = "Discord accepted unverified observation"
                    _ = write(record)
                } else if http.statusCode == 429 {
                    // Discord explicitly refused this attempt; leave it queued for a later session.
                    record.state = "pending"
                    record.note = "Rate limited; waiting for next retry"
                    _ = write(record)
                    break
                } else {
                    record.note = "Discord returned HTTP \(http.statusCode); delivery uncertain"
                    _ = write(record)
                    break
                }
            } catch {
                // The network may have delivered the message before the error.
                break
            }
        }
    }
}

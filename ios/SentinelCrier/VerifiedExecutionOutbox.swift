import Foundation
import CryptoKit

/// Separate from OCR candidate alerts. Only broker-sourced execution events belong here.
/// File protection and atomic writes preserve execution IDs across app restarts.
actor VerifiedExecutionOutbox {
    enum DeliveryState: String, Codable { case pending, uncertain, sent }
    struct Entry: Codable, Identifiable {
        var id: String { execution.deduplicationKey }
        let execution: BrokerConfirmedExecution
        var state: DeliveryState
        var discordMessageId: String?
        let recordedAt: Date
        var retryAfter: Date?
    }

    private let folder: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init?(group: String = StandaloneConfiguration.group) {
        guard let root = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: group) else { return nil }
        let target = root.appendingPathComponent("broker-confirmed-executions", isDirectory: true)
        do { try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true) }
        catch { return nil }
        folder = target
    }

    private func file(for key: String) -> URL {
        // Keys are broker-provided and cannot be used directly as filenames.
        let encoded = SHA256.hash(data: Data(key.utf8))
            .map { String(format: "%02x", $0) }.joined()
        return folder.appendingPathComponent(encoded + ".json")
    }

    private func persist(_ entry: Entry) throws {
        let data = try encoder.encode(entry)
        try data.write(to: file(for: entry.id), options: [.atomic, .completeFileProtectionUnlessOpen])
    }

    /// Ingestion must be called only after validating the event against an
    /// authenticated official broker order/fill response. It does not infer fills.
    @discardableResult
    func recordConfirmed(_ execution: BrokerConfirmedExecution) throws -> Bool {
        try execution.validate()
        let url = file(for: execution.deduplicationKey)
        guard !FileManager.default.fileExists(atPath: url.path) else { return false }
        try persist(Entry(execution: execution, state: .pending,
                          discordMessageId: nil, recordedAt: Date()))
        return true
    }

    func entries() -> [Entry] {
        guard let files = try? FileManager.default.contentsOfDirectory(at: folder,
                        includingPropertiesForKeys: nil) else { return [] }
        return files.filter { $0.pathExtension == "json" }.compactMap {
            guard let data = try? Data(contentsOf: $0) else { return nil }
            return try? decoder.decode(Entry.self, from: data)
        }.sorted { $0.recordedAt < $1.recordedAt }
    }

    /// Returns one pending entry and marks it uncertain before network I/O.
    /// A crash or timeout cannot cause an automatic duplicate Discord post.
    func claimForDelivery() throws -> Entry? {
        guard !entries().contains(where: { ($0.retryAfter ?? .distantPast) > Date() }),
              var entry = entries().first(where: { $0.state == .pending }) else { return nil }
        entry.state = .uncertain
        try persist(entry)
        return entry
    }

    func rateLimited(id: String, seconds: Double) throws {
        guard let data = try? Data(contentsOf: file(for: id)),
              var entry = try? decoder.decode(Entry.self, from: data), entry.state == .uncertain else { return }
        entry.state = .pending
        entry.retryAfter = Date().addingTimeInterval(seconds.isFinite && seconds >= 0 ? max(1, seconds) : 60)
        try persist(entry)
    }

    func confirmDelivery(id: String, discordMessageId: String) throws {
        guard !discordMessageId.isEmpty, discordMessageId.allSatisfy({ $0.isNumber }),
              let data = try? Data(contentsOf: file(for: id)),
              var entry = try? decoder.decode(Entry.self, from: data),
              entry.state == .uncertain else { return }
        entry.state = .sent
        entry.discordMessageId = discordMessageId
        try persist(entry)
    }
}

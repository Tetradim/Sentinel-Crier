import Foundation
import Security

/// Shared between the app and its user-started ReplayKit extension.
/// A Discord webhook is a secret: never store it in UserDefaults or the evidence files.
enum StandaloneConfiguration {
    static let group = "group.com.tetradim.sentinelcrier"
    private static let service = "com.tetradim.sentinelcrier.discord-webhook"
    private static let account = "webhook"
    private static let enabledKey = "standaloneCandidateAlertsEnabled"

    private static var accessGroup: String? {
        guard let value = Bundle.main.object(forInfoDictionaryKey: "CrierSharedKeychainGroup") as? String,
              !value.isEmpty, !value.contains("$(") else { return nil }
        return value
    }

    static var enabled: Bool {
        UserDefaults(suiteName: group)?.bool(forKey: enabledKey) == true
    }

    static func setEnabled(_ enabled: Bool) {
        UserDefaults(suiteName: group)?.set(enabled, forKey: enabledKey)
    }

    static func saveWebhook(_ raw: String) -> Bool {
        guard let url = URL(string: raw), url.scheme == "https",
              url.host?.lowercased() == "discord.com" || url.host?.lowercased() == "discordapp.com",
              url.path.hasPrefix("/api/webhooks/"), url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil, let group = accessGroup,
              let data = raw.data(using: .utf8) else { return false }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: group
        ]
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let result = SecItemAdd(item as CFDictionary, nil)
        if result == errSecDuplicateItem {
            return SecItemUpdate(query as CFDictionary,
                                 [kSecValueData as String: data] as CFDictionary) == errSecSuccess
        }
        return result == errSecSuccess
    }

    static func webhook() -> URL? {
        guard let group = accessGroup else { return nil }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: group,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data, let raw = String(data: data, encoding: .utf8),
              let url = URL(string: raw),
              url.scheme == "https",
              url.host?.lowercased() == "discord.com" || url.host?.lowercased() == "discordapp.com",
              url.path.hasPrefix("/api/webhooks/"), url.query == nil,
              url.fragment == nil else { return nil }
        return url
    }

    static func clear() {
        setEnabled(false)
        guard let group = accessGroup else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: group
        ]
        SecItemDelete(query as CFDictionary)
    }
}

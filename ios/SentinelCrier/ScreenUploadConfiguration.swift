import Foundation
import Security

/// Shared only between the containing app and its ReplayKit upload extension.
/// Requires Keychain Sharing entitlement on both targets and matching signing team.
enum ScreenUploadConfiguration {
    private static let group = "group.com.tetradim.sentinelcrier"
    private static let service = "com.tetradim.sentinelcrier.screen-upload"

    private static var sharedKeychainGroup: String? {
        guard let group = Bundle.main.object(forInfoDictionaryKey: "CrierSharedKeychainGroup") as? String,
              !group.isEmpty, !group.contains("$(") else { return nil }
        return group
    }

    static func configure(baseURL: URL, token: String) -> Bool {
        guard baseURL.scheme?.lowercased() == "https",
              baseURL.host != nil, baseURL.user == nil, baseURL.password == nil,
              !token.isEmpty, let bytes = token.data(using: .utf8),
              let accessGroup = sharedKeychainGroup,
              let defaults = UserDefaults(suiteName: group) else { return false }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "upload",
            kSecAttrAccessGroup as String: accessGroup
        ]
        var attributes = query
        attributes[kSecValueData as String] = bytes
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let result = SecItemAdd(attributes as CFDictionary, nil)
        if result == errSecDuplicateItem {
            let updated = SecItemUpdate(query as CFDictionary,
                                       [kSecValueData as String: bytes] as CFDictionary)
            guard updated == errSecSuccess else { return false }
        } else if result != errSecSuccess { return false }
        defaults.set(baseURL.absoluteString, forKey: "backendURL")
        return true
    }

    static func load() -> (URL, String)? {
        guard let accessGroup = sharedKeychainGroup,
              let defaults = UserDefaults(suiteName: group),
              let rawURL = defaults.string(forKey: "backendURL"),
              let url = URL(string: rawURL),
              url.scheme?.lowercased() == "https", url.host != nil,
              url.user == nil, url.password == nil else { return nil }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "upload",
            kSecAttrAccessGroup as String: accessGroup,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let bytes = result as? Data,
              let token = String(data: bytes, encoding: .utf8) else { return nil }
        return (url, token)
    }

    static func clear() {
        guard let accessGroup = sharedKeychainGroup else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "upload",
            kSecAttrAccessGroup as String: accessGroup
        ]
        SecItemDelete(query as CFDictionary)
        UserDefaults(suiteName: group)?.removeObject(forKey: "backendURL")
        // Revocation also removes observations awaiting upload.
        if let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group) {
            let folder = root.appendingPathComponent("screen-observations", isDirectory: true)
            try? FileManager.default.removeItem(at: folder)
        }
    }
}

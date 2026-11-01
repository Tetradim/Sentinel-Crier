import Foundation

/// Manual host commands never inherit a follower's resume preference. Retained
/// instructions require a new deliberate command after reconnect or bank repair.
struct IntentEntryAuthorization {
    private var hostCommands: Set<String> = []
    var hasHostCommands: Bool { !hostCommands.isEmpty }
    mutating func allowHostCommand(_ eventID: String) { hostCommands.insert(eventID) }
    mutating func revokeHostCommands() { hostCommands.removeAll() }
    func allows(eventID: String, hosting: Bool, followerPaused: Bool) -> Bool {
        hosting ? hostCommands.contains(eventID) : !followerPaused
    }
}

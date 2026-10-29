import SwiftUI

@main
struct SentinelCrierApp: App {
    var body: some Scene {
        WindowGroup {
            ConnectionRoutesRoot()
        }
    }
}

@MainActor private final class ConnectionRoutesBootstrap: ObservableObject {
    let routes: ConnectionRoutes?
    let failure: String?
    init() {
        do { routes = try ConnectionRoutes(); failure = nil }
        catch { routes = nil; failure = "Connections unavailable. Preserve app data for recovery: " + error.localizedDescription }
    }
}
struct ConnectionRoutesRoot: View {
    @StateObject private var bootstrap = ConnectionRoutesBootstrap()
    var body: some View {
        if let routes = bootstrap.routes { ConnectionRoutesShell(routes: routes) }
        else { Text(bootstrap.failure ?? "Connections unavailable").padding() }
    }
}
private struct ConnectionRoutesShell: View {
    @ObservedObject var routes: ConnectionRoutes
    var body: some View { CrierCommandCenter(model: routes.model, routes: routes) }
}

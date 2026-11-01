import SwiftUI

/// Original native SwiftUI shell: five primary tabs, with account settings
/// available from Home instead of consuming a permanent tab.
struct CrierCommandCenter: View {
    @ObservedObject var model: AlpacaWorkspace
    @ObservedObject var routes: ConnectionRoutes
    @State private var routeError = ""
    @State private var showAccountBank = false
    @StateObject private var connections = ProviderConnections()
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("CRIER").font(.caption.weight(.semibold)).tracking(2).foregroundStyle(.secondary)
                    Text(model.account.map { "Alpaca · " + String($0.id.suffix(4)) } ?? "Alpaca account").font(.title2.weight(.bold))
                }
                Spacer()
                Text(model.environment.rawValue.uppercased())
                    .font(.caption.weight(.bold)).monospaced()
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(Color.blue.opacity(0.16), in: Capsule())
                    .accessibilityLabel("Broker environment: " + model.environment.rawValue)
            }.padding(.horizontal, 16).padding(.top, 10).padding(.bottom, 8)
            HStack(spacing: 12) {
                Picker("Connection", selection: Binding(get: { routes.selected }, set: { id in
                    do { try routes.select(id) } catch { routeError = error.localizedDescription }
                })) {
                    ForEach(routes.registry.routes) { route in Text(route.name).tag(route.id) }
                }.pickerStyle(.menu).labelsHidden()
                    .font(.subheadline).lineLimit(1)
                    .frame(maxWidth: .infinity, minHeight: 44, maxHeight: 44, alignment: .leading)
                    .disabled(connections.busy)
                Button { do { try routes.add() } catch { routeError = error.localizedDescription } } label: {
                    Image(systemName: "plus.circle").frame(minWidth: 44, minHeight: 44)
                }.accessibilityLabel("Add connection").disabled(connections.busy)
                Button { showAccountBank = true } label: { Image(systemName: "number.square").frame(minWidth: 44, minHeight: 44) }.accessibilityLabel("Account ID bank")
                Button(role: .destructive) { Task { await routes.stopAll() } } label: {
                    Image(systemName: "stop.circle").frame(width: 44, height: 44)
                }.accessibilityLabel("Stop all")
                    .accessibilityHint("Stops all retained connections and workers")
            }.padding(.horizontal, 16)
            Divider()
            if !routeError.isEmpty { Text(routeError).font(.caption) }
            if !model.legacyRoute { Text("Alpaca API-key route · OAuth, Webull and Discord delivery remain on the original connection.").font(.caption).padding(.horizontal) }
        TabView {
            CrierAccountHome()
                .tabItem { Label("Home", systemImage: "building.columns") }
            CrierMarketsView()
                .tabItem { Label("Markets", systemImage: "chart.xyaxis.line") }
            AlpacaTradingView()
                .tabItem { Label(model.purpose == .follow ? "Follow" : "Trade", systemImage: "arrow.left.arrow.right") }
            CrierPositionsView()
                .tabItem { Label("Positions", systemImage: "square.stack.3d.up") }
            CrierOrdersView()
                .tabItem { Label("Orders", systemImage: "list.bullet.rectangle") }
        }
        .id(routes.selected)
        .tint(Color(red: 0.20, green: 0.52, blue: 1.0))
        .toolbarBackground(Color(red: 0.055, green: 0.065, blue: 0.085), for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
        }
        .background(Color(red: 0.035, green: 0.045, blue: 0.06))
        .sheet(isPresented: $showAccountBank) { AccountIDBankView(routes: routes) }
        .environmentObject(model)
        .environmentObject(connections)
        .onOpenURL { url in
            // Provider callbacks always belong to the original route, never the visible editor.
            if let original = routes.sessions["legacy"] {
                Task { await connections.receive(url, environment: original.environment, purpose: original.purpose == .alerts ? "alerts" : "trade") }
            }
        }
        .preferredColorScheme(.dark)
        .task(id: scenePhase) {
            connections.suspend(scenePhase != .active)
            await routes.sceneActive(scenePhase == .active)
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await routes.refresh()
                let paired = routes.sessions.values.contains { $0.intent?.connected == true }
                do { try await Task.sleep(nanoseconds: paired ? 2_000_000_000 : 15_000_000_000) } catch { return }
            }
        }
    }
}

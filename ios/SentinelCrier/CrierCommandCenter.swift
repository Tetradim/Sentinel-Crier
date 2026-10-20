import SwiftUI

/// Original native SwiftUI shell: five primary tabs, with account settings
/// available from Home instead of consuming a permanent tab.
struct CrierCommandCenter: View {
    @StateObject private var model = AlpacaWorkspace()
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        TabView {
            BrokerageOverview()
                .tabItem { Label("Home", systemImage: "house") }
            CrierMarketsView()
                .tabItem { Label("Markets", systemImage: "chart.xyaxis.line") }
            AlpacaTradingView()
                .tabItem { Label("Trade", systemImage: "arrow.left.arrow.right") }
            CrierPositionsView()
                .tabItem { Label("Positions", systemImage: "square.stack.3d.up") }
            CrierExecutionsView()
                .tabItem { Label("Alerts", systemImage: "bell") }
        }
        .environmentObject(model)
        .preferredColorScheme(.dark)
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await model.refresh()
                let paired = (try? MirrorPairing.load()) != nil
                do { try await Task.sleep(nanoseconds: paired ? 2_000_000_000 : 15_000_000_000) } catch { return }
            }
        }
    }
}

struct CrierPositionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    var body: some View {
        NavigationStack {
            List {
                Section("\(model.environment.rawValue.uppercased()) positions") {
                    if model.positions.isEmpty { Text("No positions loaded. Connect or refresh the account.") }
                    ForEach(model.positions) { position in
                        VStack(alignment: .leading) {
                            Text(position.symbol).font(.headline)
                            Text("Quantity: \(position.qty) • average $\(position.avg_entry_price)")
                            if let value = position.market_value { Text("Market value: $\(value)") }
                        }
                    }
                }
                Text(model.message).font(.footnote)
            }.navigationTitle("Positions").refreshable { await model.refresh() }
        }
    }
}
struct CrierExecutionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage("discordFillStyle") private var style = "homebrew"
    var body: some View {
        NavigationStack {
            List {
                Section("Discord fill format") {
                    Picker("Format", selection: $style) {
                        Text("Homebrew Markdown").tag("homebrew")
                        Text("Plain text").tag("plain")
                        Text("Card").tag("card")
                    }
                    Text("Only broker FILL activities are published. First connection sets a baseline; earlier history is not posted. Monitoring runs while this app is active. Uncertain deliveries need manual Discord verification and are never automatically resent.").font(.footnote)
                }
                Section("\(model.environment.rawValue.uppercased()) verified fills") {
                    ForEach(model.deliveries.reversed()) { entry in
                        VStack(alignment: .leading) {
                            Text("\(entry.fill.side.uppercased()) \(entry.fill.qty) \(entry.fill.symbol) @ $\(entry.fill.price)")
                            Text(entry.fill.transaction_time).font(.caption)
                            Text("Discord: \(entry.state)").font(.caption)
                            Text(entry.fill.id).font(.caption).textSelection(.enabled)
                        }
                    }
                }
                Text(model.message).font(.footnote)
            }.navigationTitle("Alerts").refreshable { await model.refresh() }
        }
    }
}

struct CrierConnectionsView: View {
    @State private var webhook = ""
    @State private var configured = StandaloneConfiguration.webhook() != nil
    @State private var feedback: String?

    var body: some View {
        Form {
            AlpacaConnectionForm()
            Section("Preferences") {
                NavigationLink("Trading settings", destination: CrierSettingsView())
            }
            Section("Discord webhook") {
                SecureField("Discord webhook URL", text: $webhook)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save webhook") {
                    configured = StandaloneConfiguration.saveWebhook(
                        webhook.trimmingCharacters(in: .whitespacesAndNewlines))
                    feedback = configured ? "Webhook saved securely." : "Invalid webhook or Keychain unavailable."
                    webhook = ""
                }
                Text(configured ? "Configured" : "Not configured")
                    .foregroundStyle(configured ? .green : .secondary)
                Button("Remove webhook", role: .destructive) {
                    StandaloneConfiguration.clear()
                    configured = false
                    feedback = "Webhook removed."
                }
                if let feedback { Text(feedback).font(.footnote) }
            }
        }
        .navigationTitle("Connections")
    }
}

struct CrierSettingsView: View {
    @AppStorage(TradingPreferences.autoStopsKey) private var autoStops = false
    @AppStorage(TradingPreferences.autoTakeProfitKey) private var autoTakeProfit = false
    @AppStorage(TradingPreferences.automatedDiscordTradingKey) private var automatedDiscord = false

    var body: some View {
        Form {
            Section("Optional trading controls") {
                Toggle("Automatic stop orders", isOn: $autoStops).disabled(true)
                Toggle("Automatic take-profit orders", isOn: $autoTakeProfit).disabled(true)
                Toggle("Discord-triggered automatic trading", isOn: $automatedDiscord).disabled(true)
                Text("These are preference placeholders only. These automatic order strategies are not implemented. Manual Alpaca orders are available from Trade. All optional controls default to off.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Execution safeguards") {
                Label("Final order confirmation required", systemImage: "checkmark.shield")
                Label("Broker order reconciliation required", systemImage: "arrow.triangle.2.circlepath")
                Text("Idempotency, broker permissions, authenticated execution evidence and audit logging are mandatory and cannot be disabled.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Settings")
    }
}

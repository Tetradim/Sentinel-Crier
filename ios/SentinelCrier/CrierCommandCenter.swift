import SwiftUI

/// Original native SwiftUI shell: five primary tabs, with account settings
/// available from Home instead of consuming a permanent tab.
struct CrierCommandCenter: View {
    var body: some View {
        TabView {
            BrokerageOverview()
                .tabItem { Label("Home", systemImage: "house") }
            CrierMarketsView()
                .tabItem { Label("Markets", systemImage: "chart.xyaxis.line") }
            LiveTradingHome()
                .tabItem { Label("Trade", systemImage: "arrow.left.arrow.right") }
            CrierPositionsView()
                .tabItem { Label("Positions", systemImage: "square.stack.3d.up") }
            CrierExecutionsView()
                .tabItem { Label("Alerts", systemImage: "bell") }
        }
        .preferredColorScheme(.dark)
    }
}

struct CrierPositionsView: View {
    var body: some View {
        NavigationStack {
            List {
                Section("All Accounts") {
                    Label("No brokerage positions available", systemImage: "square.stack.3d.up")
                        .foregroundStyle(.secondary)
                    Text("Trade Groups will show each brokerage's real position quantity and independent fill status. Coordinated closes require a fresh broker position check.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Positions")
        }
    }
}

struct CrierExecutionsView: View {
    @State private var executions: [VerifiedExecutionOutbox.Entry] = []

    var body: some View {
        NavigationStack {
            List {
                Section("Verified executions") {
                    if executions.isEmpty {
                        Label("No confirmed fills yet", systemImage: "checkmark.seal")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(executions) { entry in
                        VStack(alignment: .leading, spacing: 4) {
                            let execution = entry.execution
                            Text("\(execution.contract.underlying) \(execution.contract.expiration) \(execution.contract.strike)\(execution.contract.right)")
                                .font(.headline)
                            Text("\(execution.action.rawValue) · \(execution.incrementalQuantity) @ $\(execution.executionPrice)")
                            Text("\(execution.brokerId) · Discord \(entry.state.rawValue)")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("Discord trading signals") {
                    Text("Incoming signal channels will be available after approved Discord intake and source permissions are configured. Messages will prepare tickets, not automatically execute trades.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Alerts")
            .task { await refresh() }
            .refreshable { await refresh() }
        }
    }

    @MainActor
    private func refresh() async {
        guard let outbox = VerifiedExecutionOutbox() else { return }
        executions = Array(await outbox.entries().reversed())
    }
}

struct CrierConnectionsView: View {
    @State private var webhook = ""
    @State private var configured = StandaloneConfiguration.webhook() != nil
    @State private var feedback: String?

    var body: some View {
        Form {
            Section("Live broker connections") {
                ForEach(["Webull", "Alpaca", "Tradier"], id: \.self) { name in
                    HStack {
                        Text(name)
                        Spacer()
                        Text("Not connected").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Text("Official broker authorization requires developer approval and a secure cloud backend. Brokerage passwords are never entered into Crier.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
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
                Text("These are preference placeholders only. No automation is active or connected to a broker in this build. All optional controls default to off.")
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

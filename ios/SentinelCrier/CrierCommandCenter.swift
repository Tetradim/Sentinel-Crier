import SwiftUI

/// Customer-facing live brokerage shell. Legacy screen observations are not
/// presented as trades and cannot be used as execution evidence.
struct CrierCommandCenter: View {
    @State private var webhook = ""
    @State private var webhookConfigured = StandaloneConfiguration.webhook() != nil
    @State private var statusMessage: String?
    @State private var executions: [VerifiedExecutionOutbox.Entry] = []

    var body: some View {
        TabView {
            LiveTradingHome()
                .tabItem { Label("Trade", systemImage: "chart.line.uptrend.xyaxis") }
            NavigationStack { positions }
                .tabItem { Label("Positions", systemImage: "square.stack.3d.up") }
            NavigationStack { alerts }
                .tabItem { Label("Executions", systemImage: "checkmark.seal") }
            NavigationStack { connections }
                .tabItem { Label("Connections", systemImage: "link") }
        }
        .preferredColorScheme(.dark)
        .task { await refreshExecutions() }
    }

    private var positions: some View {
        List {
            Section("Live accounts") {
                Label("No authorized brokerage connected", systemImage: "building.columns")
                Text("Positions and open orders will load directly from the connected brokerage. No locally invented positions are shown.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Positions")
    }

    private var alerts: some View {
        List {
            Section("Broker-confirmed executions") {
                if executions.isEmpty {
                    Text("No broker-confirmed executions recorded.")
                        .foregroundStyle(.secondary)
                }
                ForEach(executions) { entry in
                    VStack(alignment: .leading, spacing: 5) {
                        let e = entry.execution
                        Text("\(e.contract.underlying) \(e.contract.expiration) \(e.contract.strike)\(e.contract.right)")
                            .font(.headline)
                        Text("\(e.action.rawValue) · \(e.incrementalQuantity) @ $\(e.executionPrice)")
                        Text("\(e.brokerId) · \(entry.state.rawValue)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Section("Delivery policy") {
                Text("Only broker-confirmed incremental fills qualify. Ambiguous Discord deliveries are never automatically resent.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Executions")
        .refreshable { await refreshExecutions() }
    }

    private var connections: some View {
        Form {
            Section("Brokerage APIs") {
                Label("Webull — authorization required", systemImage: "lock.shield")
                Label("Alpaca — authorization required", systemImage: "lock.shield")
                Label("Tradier — authorization required", systemImage: "lock.shield")
                Text("Official brokerage credentials and any required developer approvals must be provisioned before live orders can be enabled. The app does not request brokerage passwords.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Discord execution destination") {
                SecureField("Discord webhook URL", text: $webhook)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save Discord webhook") {
                    webhookConfigured = StandaloneConfiguration.saveWebhook(
                        webhook.trimmingCharacters(in: .whitespacesAndNewlines))
                    statusMessage = webhookConfigured ? "Webhook saved in Keychain." : "Invalid webhook or Keychain unavailable."
                    webhook = ""
                }
                Text(webhookConfigured ? "Configured" : "Not configured")
                    .foregroundStyle(webhookConfigured ? .green : .orange)
                Button("Remove Discord webhook", role: .destructive) {
                    StandaloneConfiguration.clear()
                    webhookConfigured = false
                    statusMessage = "Webhook removed."
                }
                if let statusMessage { Text(statusMessage).font(.footnote) }
                Text("Discord publishing starts only when a connected brokerage supplies verified execution events.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Connections")
    }

    @MainActor
    private func refreshExecutions() async {
        guard let outbox = VerifiedExecutionOutbox() else { return }
        executions = Array(await outbox.entries().reversed())
    }
}

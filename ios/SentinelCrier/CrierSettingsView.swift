import SwiftUI

struct CrierSettingsView: View {
    var body: some View {
        Form {
            Section("Supported trading") {
                Label("Manual Alpaca day limit orders", systemImage: "hand.tap")
                Text("Buy whole shares or standard 100-share option contracts; sell existing long holdings. Options require level 2 permission in your Alpaca account. Enter your own limit price in Trade.")
                    .font(.footnote).foregroundStyle(.secondary)
                Label("Host or follow paired trades", systemImage: "link")
                Text("Set up a remote connection in Connections. Keep Crier open to follow trades and deliver fill alerts.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Execution safeguards") {
                Label("Final order confirmation required", systemImage: "checkmark.shield")
                Label("Broker order reconciliation required", systemImage: "arrow.triangle.2.circlepath")
                Text("Idempotency, broker permissions, authenticated execution evidence and audit logging are mandatory and cannot be disabled.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Trading capabilities")
    }
}

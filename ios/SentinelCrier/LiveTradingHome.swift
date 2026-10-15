import SwiftUI

/// Real-account interface: empty states are truthful until approved API access
/// is provisioned. No fabricated prices, balances, trades or order controls.
struct LiveTradingHome: View {
    @State private var symbol = ""
    @State private var expiration = Date()
    @State private var selectedTab = 0

    var body: some View {
        NavigationStack {
            List {
                Section("Account") {
                    Label("Connect an authorized brokerage", systemImage: "building.columns")
                        .font(.headline)
                    Text("No brokerage authorization has been configured. Balances, positions and live orders will appear only after an official API connection is established.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Markets") {
                    TextField("Ticker symbol", text: $symbol)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    DatePicker("Option expiration", selection: $expiration, displayedComponents: .date)
                    Label("Live market data connection required", systemImage: "chart.xyaxis.line")
                        .foregroundStyle(.secondary)
                    Text("Quotes and option contracts are never estimated or populated with demonstration prices.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Live order ticket") {
                    Label("Unavailable until broker authorization", systemImage: "lock.shield")
                        .foregroundStyle(.orange)
                    Text("An order must use a broker-resolved contract, a current broker preview and a separate explicit customer confirmation. Submission cannot be enabled by selecting a ticker alone.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Positions and orders") {
                    Label("No connected account", systemImage: "list.bullet.rectangle")
                        .foregroundStyle(.secondary)
                    Text("Live positions and order status are retrieved from the connected broker; local assumptions cannot substitute for broker records.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Discord") {
                    Label("Broker-confirmed executions only", systemImage: "checkmark.seal")
                    Text("A submitted order is not a fill. Alerts require actual execution IDs, incremental quantities and execution prices.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Trade")
        }
    }
}

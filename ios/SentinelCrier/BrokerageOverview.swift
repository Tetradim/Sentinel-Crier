import SwiftUI

/// Read-only overview of the connected Alpaca account and foreground limits.
struct BrokerageOverview: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage(TradingPreferences.hideBalancesKey) private var hideBalances = false
    var body: some View {
        NavigationStack {
            List {
                Section(model.environment == .paper ? "Alpaca Paper: simulated funds" : "Alpaca Live: real money") {
                    if let account = model.account {
                        Text("Account loaded; broker status: \(account.status)")
                        Text("Equity: \(hideBalances ? "••••" : "$" + account.equity)")
                        Text("Buying power: \(hideBalances ? "••••" : "$" + account.buying_power)")
                        Toggle("Hide balances", isOn: $hideBalances)
                    } else {
                        Text("No account connected. Open Connections and use Alpaca API keys for the selected paper or live account.")
                        NavigationLink("Connect Alpaca", destination: CrierConnectionsView())
                    }
                    if let time = model.updatedAt { Text("Updated \(time.formatted())").font(.caption) }
                    Text(model.message).font(.footnote)
                }
                Section("Monitoring") {
                    Text("Keep Crier open to monitor orders and fills and deliver Discord alerts. iOS suspension pauses this work until you return. Reopening catches up fills since the saved baseline.")
                    Text("A connected Alpaca account is required. Discord alerts also need a webhook in Connections; following trades needs a paired remote connection.").font(.footnote)
                    Text("Trade supports manual day limit orders for whole shares and standard options, with sales limited to existing long holdings. Options require Alpaca level 2 permission.").font(.footnote)
                }
            }.navigationTitle("Home")
                .refreshable { await model.refresh() }
                .toolbar {
                    NavigationLink(destination: CrierConnectionsView()) { Label("Connections", systemImage: "person.crop.circle") }.accessibilityLabel("Connections and settings")
                }
        }
    }
}

struct CrierMarketsView: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    TradingChartWorkspace()
                    HStack {
                        Image(systemName: "lock.shield")
                            .foregroundStyle(.secondary)
                        Text("This chart workspace is not an Alpaca quote feed. Discover tradable option contracts in Trade; live bid/ask quotes are not implemented.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
            }
            .navigationTitle("Markets")
        }
    }
}

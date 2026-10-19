import SwiftUI

/// Fast, read-only account overview. Empty state is deliberate until the
/// authorized cloud broker snapshot endpoint has been provisioned.
struct BrokerageOverview: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage(TradingPreferences.hideBalancesKey) private var hideBalances = false
    var body: some View {
        NavigationStack {
            List {
                Section("Alpaca • \(model.environment.rawValue.uppercased())") {
                    if let account = model.account {
                        Text("Account status: \(account.status)")
                        Text("Equity: \(hideBalances ? "••••" : "$" + account.equity)")
                        Text("Buying power: \(hideBalances ? "••••" : "$" + account.buying_power)")
                        Toggle("Hide balances", isOn: $hideBalances)
                    } else { Text("Connect API credentials in Connections.") }
                    if let time = model.updatedAt { Text("Updated \(time.formatted())").font(.caption) }
                    Text(model.message).font(.footnote)
                }
                Section("Monitoring") {
                    Text("Orders and fills refresh every 15 seconds while the app is active. Reopening catches up fills since the saved baseline. iOS suspension stops monitoring and Discord delivery until you return.")
                    Text("Webull Connect approval pending. Automated signals, stops and profit orders are unavailable.").font(.footnote)
                }
            }.navigationTitle("Home")
                .refreshable { await model.refresh() }
                .toolbar {
                    NavigationLink(destination: CrierConnectionsView()) { Image(systemName: "person.crop.circle") }.accessibilityLabel("Connections and settings")
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

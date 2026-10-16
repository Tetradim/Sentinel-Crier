import SwiftUI

/// Fast, read-only account overview. Empty state is deliberate until the
/// authorized cloud broker snapshot endpoint has been provisioned.
struct BrokerageOverview: View {
    @AppStorage(TradingPreferences.hideBalancesKey) private var hideBalances = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("All Accounts").font(.title2.bold())
                            Text("No connected brokerage accounts")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button {
                            hideBalances.toggle()
                        } label: {
                            Image(systemName: hideBalances ? "eye.slash" : "eye")
                        }
                        .accessibilityLabel(hideBalances ? "Show balances" : "Hide balances")
                    }
                    HStack {
                        VStack(alignment: .leading) {
                            Text("Total equity").font(.caption).foregroundStyle(.secondary)
                            Text(hideBalances ? "••••••" : "Unavailable")
                                .font(.title3.weight(.semibold))
                        }
                        Spacer()
                        VStack(alignment: .trailing) {
                            Text("Buying power").font(.caption).foregroundStyle(.secondary)
                            Text(hideBalances ? "••••••" : "Unavailable")
                                .font(.title3.weight(.semibold))
                        }
                    }
                }
                Section("Connected brokerages") {
                    Label("Connect a broker to see live balances", systemImage: "building.columns")
                        .foregroundStyle(.secondary)
                    Text("Crier will display timestamped live account data when its official broker connections are active. A delayed account must not block the entire dashboard.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Activity") {
                    Label("No live trading activity to display", systemImage: "bolt.horizontal.circle")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Home")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: CrierConnectionsView()) {
                        Image(systemName: "person.crop.circle")
                    }
                    .accessibilityLabel("Connections and settings")
                }
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
                        Text("Quotes, option chains and contracts will be shown only after live data licensing and broker APIs are connected.")
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

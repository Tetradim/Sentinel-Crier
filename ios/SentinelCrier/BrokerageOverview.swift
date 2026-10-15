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
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        NavigationLink("Connections", destination: CrierConnectionsView())
                        NavigationLink("Settings", destination: CrierSettingsView())
                    } label: {
                        Image(systemName: "person.crop.circle")
                    }
                    .accessibilityLabel("Account menu")
                }
            }
        }
    }
}

struct CrierMarketsView: View {
    @State private var symbol = ""
    @AppStorage(TradingPreferences.advancedChartToolsKey) private var advancedTools = false

    var body: some View {
        NavigationStack {
            List {
                Section("Find a stock or option") {
                    TextField("Search ticker", text: $symbol)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    Label("Live market data not connected", systemImage: "chart.line.uptrend.xyaxis")
                        .foregroundStyle(.secondary)
                }
                Section("Charts") {
                    Toggle("Advanced chart tools", isOn: $advancedTools)
                    Text("Price charts will load only for the selected instrument. Advanced indicators are optional and off by default.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Options chain") {
                    Text("Select a supported brokerage connection to retrieve a live, broker-resolved options chain.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Markets")
        }
    }
}

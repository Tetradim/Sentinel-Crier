import SwiftUI

/// Live brokerage workspace. No invented quotes, balances, positions, or fills.
/// Connections and order entry remain unavailable until approved API adapters exist.
struct LiveTradingHome: View {
    var body: some View {
        NavigationStack {
            List {
                Section("Brokerage accounts") {
                    Label("No authorized brokerage connected", systemImage: "building.columns")
                        .foregroundStyle(.secondary)
                    Text("Trading requires an approved, official broker API connection. Account authorization is not configured in this build.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Markets and options") {
                    Label("Live option chains unavailable", systemImage: "chart.xyaxis.line")
                        .foregroundStyle(.secondary)
                    Text("Contract selection and quotes will be shown only when provided by a connected brokerage or licensed market-data service.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Place an order") {
                    Label("Live order entry unavailable", systemImage: "lock.shield")
                        .foregroundStyle(.orange)
                    Text("No order can be placed until account authorization, broker capability checks, an order preview, and explicit confirmation are implemented.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section("Discord execution alerts") {
                    Label("Broker-confirmed fills only", systemImage: "checkmark.seal")
                    Text("Order submission is not a fill. Execution alerts require a broker execution identifier, actual quantity, and actual execution price.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Trade")
        }
    }
}

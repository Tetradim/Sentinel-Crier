import SwiftUI

struct CrierPositionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var symbolQuery = ""
    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Label(model.environment.rawValue.uppercased(), systemImage: "building.columns")
                            .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer()
                        Text("\(model.positions.count) loaded").font(.caption).foregroundStyle(.secondary)
                    }.listRowBackground(Color.clear)
                    if model.positions.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("No positions loaded").font(.headline)
                            Text("Connect your account, or pull down to refresh. This view shows the last loaded broker snapshot.")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 12)
                    } else if !model.positions.contains(where: { symbolQuery.isEmpty || $0.symbol.localizedCaseInsensitiveContains(symbolQuery) }) {
                        Text("No symbols match your search.").foregroundStyle(.secondary)
                    }
                    ForEach(model.positions.filter { symbolQuery.isEmpty || $0.symbol.localizedCaseInsensitiveContains(symbolQuery) }) { position in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(position.symbol).font(.headline).textSelection(.enabled)
                                Spacer(minLength: 12)
                                VStack(alignment: .trailing, spacing: 3) {
                                    Text(position.market_value.map { "$" + $0 } ?? "—")
                                        .font(.headline).monospacedDigit()
                                    Text("Market value").font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            HStack {
                                Text("Qty \(position.qty)")
                                Spacer()
                                Text("Avg $\(position.avg_entry_price)")
                            }.font(.subheadline).monospacedDigit().foregroundStyle(.secondary)
                        }.padding(.vertical, 6)
                            .accessibilityElement(children: .combine)
                    }
                }
                Text(model.message).font(.footnote)
            }.listStyle(.plain)
                .scrollContentBackground(.hidden)
                .background(Color(red: 0.035, green: 0.045, blue: 0.06))
                .navigationTitle("Positions").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        NavigationLink(destination: CrierRecoveryView()) {
                            Label("Recovery", systemImage: "cross.case")
                        }
                    }
                }
                .searchable(text: $symbolQuery, prompt: "Search held symbols")
                .refreshable { await model.refresh() }
        }
    }
}

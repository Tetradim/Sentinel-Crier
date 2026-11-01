import SwiftUI

/// Account-first overview. Values come only from the loaded broker snapshot.
struct CrierAccountHome: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage(TradingPreferences.hideBalancesKey) private var hideBalances = false
    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Text("TOTAL ACCOUNT VALUE").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                            Spacer()
                            Button { hideBalances.toggle() } label: {
                                Image(systemName: hideBalances ? "eye.slash" : "eye").frame(width: 44, height: 44)
                            }.accessibilityLabel(hideBalances ? "Show balances" : "Hide balances")
                        }
                        Text(hideBalances ? "••••" : model.account.map { "$" + $0.equity } ?? "—")
                            .font(.system(.largeTitle, design: .rounded).weight(.semibold)).monospacedDigit()
                        HStack(alignment: .top, spacing: 24) {
                            accountValue("Buying power", value: model.account?.buying_power)
                            accountValue("Cash", value: model.account?.cash)
                        }
                        if let updated = model.updatedAt {
                            Text("Broker snapshot · " + updated.formatted(date: .omitted, time: .standard)).font(.caption).foregroundStyle(.secondary)
                        } else {
                            Text("Connect to load your account balances and holdings.").font(.subheadline).foregroundStyle(.secondary)
                        }
                    }.padding(.vertical, 8)
                }
                Section {
                    HStack {
                        Label("Positions", systemImage: "square.stack.3d.up")
                        Spacer()
                        Text("\(model.positions.count) loaded").monospacedDigit().foregroundStyle(.secondary)
                    }
                    HStack {
                        Label("Saved orders", systemImage: "list.bullet.rectangle")
                        Spacer()
                        Text("\(model.submissions.count) loaded").monospacedDigit().foregroundStyle(.secondary)
                    }
                    Text(model.message).font(.footnote).foregroundStyle(.secondary)
                } header: { Text("Account activity") }
                Section {
                    NavigationLink(destination: GuidedSetupView()) { Label("Setup & connections", systemImage: "person.crop.circle") }
                    NavigationLink(destination: CrierExecutionsView()) { Label("Fill alerts", systemImage: "bell") }.disabled(!model.legacyRoute)
                    NavigationLink(destination: PracticeGuideView()) { Label("Optional paper practice", systemImage: "book") }.accessibilityIdentifier("open-practice-guide")
                    DisclosureGroup("Health & recovery") {
                        NavigationLink("Connection health", destination: NativeHealthView())
                        NavigationLink("Original order evidence", destination: CrierRecoveryView())
                    }
                }
                Text(model.environment == .paper ? "PAPER · simulated funds" : "LIVE · real money")
                    .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            }
            .listStyle(.plain).scrollContentBackground(.hidden)
            .background(Color(red: 0.035, green: 0.045, blue: 0.06))
            .navigationTitle("Account").navigationBarTitleDisplayMode(.inline)
            .refreshable { await model.refresh() }
        }
    }
    private func accountValue(_ title: String, value: String?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(hideBalances ? "••••" : value.map { "$" + $0 } ?? "—").font(.subheadline.weight(.semibold)).monospacedDigit()
        }.accessibilityElement(children: .combine)
    }
}

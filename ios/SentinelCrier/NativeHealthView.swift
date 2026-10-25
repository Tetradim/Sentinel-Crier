import SwiftUI

struct NativeHealthView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var refresh = UUID()
    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { _ in
            List {
                Section("Observed connection checks") {
                    Text("Saved successes do not resume monitoring or grant trading permission. Idle means no queued work, not proven connectivity.")
                    if model.health.unavailable { Text("Health history unavailable; observations may be incomplete. Trading journals remain retained.").foregroundStyle(.orange) }
                    Text(model.lifecycle).font(.caption)
                }
                ForEach(model.health.snapshot()) { row in
                    Section(row.component.label) {
                        Text(row.state.replacingOccurrences(of: "_", with: " ").capitalized).font(.headline)
                        if let success = row.lastSuccess {
                            LabeledContent("Last success", value: success.formatted(date: .abbreviated, time: .standard))
                        } else { Text("Never confirmed") }
                        Text("Last result: " + (row.reason?.rawValue.replacingOccurrences(of: "_", with: " ") ?? "Not checked")).font(.caption)
                        Text(row.recovery).font(.footnote)
                    }
                }
                Section("Recovery") {
                    NavigationLink("Account setup and reconnect", destination: CrierConnectionsView())
                    NavigationLink("Orders and tracked trade evidence", destination: AlpacaTradingView())
                    NavigationLink("Discord delivery history", destination: CrierExecutionsView())
                    Button("Refresh view") { refresh = UUID() }
                    Button("Disconnect local monitoring", role: .destructive) { model.disconnect() }.disabled(model.busy || model.account == nil)
                    Text("Disconnecting retains journals and existing brokerage orders. Inspect uncertain orders/messages before retrying. iOS suspension stops local monitoring; return and reconnect or reconcile explicitly.").font(.footnote)
                }
            }.id(refresh)
        }.navigationTitle("Connection health")
    }
}

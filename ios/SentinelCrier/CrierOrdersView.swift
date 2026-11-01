import SwiftUI

struct CrierOrdersView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var workingOnly = false
    private let terminal: Set<String> = ["filled", "canceled", "expired", "rejected", "replaced"]
    private var orders: [AlpacaJournal.Submission] {
        model.submissions.reversed().filter { !workingOnly || !terminal.contains($0.state) }
    }
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Saved order filter", selection: $workingOnly) {
                        Text("All saved").tag(false)
                        Text("Working / unresolved").tag(true)
                    }.pickerStyle(.segmented)
                    Text("Original client IDs · pull down to reconcile").font(.caption).foregroundStyle(.secondary)
                    if orders.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("No saved orders loaded").font(.headline)
                            Text("Connect the original account to load retained records. Broker orders from other activity are not shown here.").font(.subheadline).foregroundStyle(.secondary)
                        }.padding(.vertical, 16)
                    }
                    ForEach(orders) { submission in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(submission.ticket.symbol).font(.headline)
                                Spacer()
                                Text(submission.state.replacingOccurrences(of: "_", with: " ")).font(.caption.weight(.semibold))
                            }
                            HStack {
                                Text(submission.ticket.side.uppercased()).foregroundStyle(submission.ticket.side == "buy" ? Color.green : Color.red)
                                Text("\(submission.ticket.quantity) @ $" + NSDecimalNumber(decimal: submission.ticket.limitPrice).stringValue)
                                Spacer()
                                Text("Filled " + (submission.order?.filled_qty ?? "—"))
                            }.font(.subheadline).monospacedDigit()
                            DisclosureGroup("Order details") {
                                Text("Client ID: " + submission.id).font(.caption).textSelection(.enabled)
                                if let order = submission.order {
                                    Text("Broker ID: " + order.id).font(.caption).textSelection(.enabled)
                                    if !terminal.contains(order.status) {
                                        Button("Request cancellation", role: .destructive) { Task { await model.cancel(submission) } }.frame(minHeight: 44).disabled(model.busy)
                                    }
                                } else {
                                    Text("Outcome unresolved. Reconcile this ID before submitting another order.").font(.caption)
                                }
                            }
                        }.padding(.vertical, 8)
                    }
                }
                if let controller = model.intent {
                    IntentTradesView(controller: controller)
                }
                Text(model.message).font(.footnote).foregroundStyle(.secondary)
            }.listStyle(.plain).scrollContentBackground(.hidden)
                .background(Color(red: 0.035, green: 0.045, blue: 0.06))
                .navigationTitle("Orders").navigationBarTitleDisplayMode(.inline)
                .toolbar { NavigationLink(destination: CrierRecoveryView()) { Label("Recovery", systemImage: "cross.case") } }
                .refreshable { await model.refresh() }
        }
    }
}

import SwiftUI

/// Observational recovery entry point. No refresh, order, cancel or reset action.
struct CrierRecoveryView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    var body: some View {
        List {
            Section("Evidence scope") {
                Label("Local records, not a fresh broker check", systemImage: "doc.text.magnifyingglass")
                    .font(.headline)
                Text("Environment: " + model.environment.rawValue.uppercased())
                if let account = model.account {
                    Text("Account: " + account.id).font(.caption).textSelection(.enabled)
                } else {
                    Text("Reconnect the original account and connection to inspect its retained journal. An empty view does not prove there are no broker orders.")
                }
                if let updated = model.updatedAt {
                    Text("Last workspace update: " + updated.formatted(date: .abbreviated, time: .standard))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Text("This screen does not submit, cancel, retry, clear IDs or resume trading. The shared-account ID bank currently runs on Windows.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Read-only broker check") {
                Button("Check latest 100 saved manual orders") { Task { await model.checkRecoveryEvidence() } }
                    .disabled(model.busy || model.account == nil)
                Text("Reads the connected account, positions and original order IDs. It does not reconcile paired trades, change the journal or grant execution permission. Positions and orders are separate timestamped reads, not an atomic broker snapshot.")
                    .font(.caption).foregroundStyle(.secondary)
                Text(model.message).font(.footnote)
                if let snapshot = model.recoverySnapshot, snapshot.accountID == model.account?.id,
                   snapshot.environment == model.environment {
                    Text("Check completed: " + snapshot.checkedAt.formatted(date: .abbreviated, time: .standard)).font(.caption)
                    ForEach(snapshot.orders) { evidence in
                        VStack(alignment: .leading, spacing: 5) {
                            Text(evidence.ticket.symbol).font(.headline)
                            Text("Client ID: " + evidence.id).font(.caption).textSelection(.enabled)
                            Text("Requested: \(evidence.ticket.quantity) · recorded locally: \(model.submissions.first(where: { $0.id == evidence.id })?.state ?? "unavailable")").font(.caption)
                            if let order = evidence.order {
                                Text("Broker: \(order.status) · filled \(order.filled_qty)").monospacedDigit()
                            } else {
                                Text("Not returned by broker. Outcome remains unresolved; do not resubmit.").foregroundStyle(.orange)
                            }
                        }
                    }
                    ForEach(snapshot.positions) { position in
                        Text("Broker position: \(position.symbol) · \(position.qty)").font(.caption).monospacedDigit()
                    }
                    Text("Broker positions include all account activity. They are not assigned to a host by this check.").font(.caption)
                }
            }
            Section("Recovery steps") {
                Label("Pause new entries on affected connections", systemImage: "pause.circle")
                Label("Verify the account and paper/live environment", systemImage: "building.columns")
                Label("Look up the original client ID in broker orders", systemImage: "number")
                Text("An unknown result can mean the broker accepted an order. Do not submit a replacement solely because confirmation is missing. Partial fills remain holdings after cancellation.")
                Text("Preserve app data and original connection journals. Never reinstall or delete IDs to bypass a reconciliation block.")
            }
            Section("Loaded manual order records · latest 100") {
                if model.submissions.isEmpty {
                    Text("No order records are loaded for this workspace. Check the original broker account before drawing conclusions.")
                        .foregroundStyle(.secondary)
                }
                ForEach(Array(model.submissions.reversed().prefix(100))) { submission in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(submission.ticket.symbol).font(.headline)
                            Spacer()
                            Text(submission.state).font(.caption)
                        }
                        Text("Client ID: " + submission.id).font(.caption).textSelection(.enabled)
                        if let order = submission.order {
                            Text("Broker ID: " + order.id).font(.caption).textSelection(.enabled)
                            Text("Recorded status: \(order.status) · filled \(order.filled_qty)")
                                .font(.subheadline).monospacedDigit()
                        } else {
                            Text("No broker order is recorded here. This alone does not establish rejection.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }.padding(.vertical, 5)
                }
            }
            if let controller = model.intent {
                CrierRecoveryTradeLinks(controller: controller)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(Color(red: 0.035, green: 0.045, blue: 0.06))
        .navigationTitle("Recovery").navigationBarTitleDisplayMode(.inline)
    }
}

private struct CrierRecoveryTradeLinks: View {
    @ObservedObject var controller: IntentController
    var body: some View {
        Section("Paired execution diagnostics · up to 100 IDs") {
            if controller.state.trades.isEmpty {
                Text("No paired trade records are loaded.").foregroundStyle(.secondary)
            }
            ForEach(Array(controller.state.trades.keys.sorted().prefix(100)), id: \.self) { tradeID in
                NavigationLink(destination: IntentDiagnosticsView(controller: controller, tradeID: tradeID)) {
                    Text(tradeID).font(.caption).monospaced()
                }
            }
        }
    }
}

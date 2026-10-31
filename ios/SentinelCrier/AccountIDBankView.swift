import SwiftUI

struct AccountIDBankView: View {
    @ObservedObject var routes: ConnectionRoutes
    @State private var snapshot: AccountIDBank.Account?
    @State private var asset = "stock"
    @State private var mode = "dollars"
    @State private var value = "0"
    @State private var fee = "0"
    @State private var message = ""
    @State private var working = false
    @Environment(\.dismiss) private var dismiss
    private func refresh() {
        do {
            snapshot = try routes.model.bankSnapshot()
            let policy = snapshot?.policies[routes.selected + ":" + asset]
            mode = policy?.mode ?? "dollars"; value = policy?.value ?? "0"; fee = policy?.fee ?? "0"
            message = "Local evidence loaded. Broker recovery requires reconnecting the original route."
        } catch { snapshot = nil; message = error.localizedDescription }
    }
    private func check(repair: Bool) {
        working = true
        Task { @MainActor in
            defer { working = false }
            do { try await routes.checkBank(repair: repair); refresh(); message = routes.model.message }
            catch { refresh(); message = error.localizedDescription }
        }
    }
    var body: some View {
        NavigationStack {
            Form {
                Section("Account ID bank") {
                    Text("Several hosts can share one Alpaca account on this installation. Each route keeps its own holdings, entry pool and recovery history.")
                    Text("Setup stops all connections, checks original orders and requires all older Crier holdings to be closed. New pools default to zero; reconnect and explicitly resume each route afterward.").font(.caption)
                    Button("Set up account ID bank") {
                        working = true
                        Task { @MainActor in
                            defer { working = false }
                            do { try await routes.setupBank(); refresh(); message = routes.model.message }
                            catch { message = error.localizedDescription }
                        }
                    }.disabled(working)
                    Button("Refresh local bank") { refresh() }.disabled(working)
                    Text(message).font(.caption).textSelection(.enabled)
                }
                if let snapshot {
                    Section("Pool for selected connection") {
                        Text(routes.registry.routes.first { $0.id == routes.selected }?.name ?? routes.selected)
                        Picker("Asset", selection: $asset) { Text("Stocks").tag("stock"); Text("Options").tag("option") }
                            .onChange(of: asset) { _ in refresh() }
                        Picker("Pool", selection: $mode) {
                            Text("Units").tag("units"); Text("Dollars").tag("dollars"); Text("Equity percent").tag("equity_percent")
                        }
                        TextField("Pool value", text: $value).keyboardType(.decimalPad)
                        TextField("Fee reserve per order", text: $fee).keyboardType(.decimalPad)
                        Button("Save host pool") {
                            do { try routes.model.configureBank(asset: asset, mode: mode, value: value, fee: fee); refresh(); message = "Pool saved. Orders remain under the route's explicit entry controls." }
                            catch { message = error.localizedDescription }
                        }.disabled(working)
                    }
                    Section("Account evidence") {
                        Button("Check original broker IDs and holdings") { check(repair: false) }.disabled(working)
                        Button("Repair after verified flat reconciliation") { check(repair: true) }.disabled(working)
                        Text("Repair stops all routes and verifies every original order and unchanged external inventory. It refuses unresolved orders or any host holdings; it retains every ID and source identity.").font(.caption)
                        Text("Local cash ledger: " + NSDecimalNumber(decimal: snapshot.available).stringValue)
                        Text("Ledger amounts require current broker reconciliation before order admission.").font(.caption)
                        Text(snapshot.blocked.isEmpty ? "No retained account block" : "Blocked: " + snapshot.blocked)
                        ForEach(snapshot.lots.sorted { $0.id > $1.id }.prefix(100)) { lot in
                            VStack(alignment: .leading) {
                                Text("ID \(lot.id) · " + (lot.active ? "Active" : "Archived"))
                                Text(lot.symbol).font(.caption)
                                Text("Owner: " + lot.route).font(.caption).textSelection(.enabled)
                                let orders = snapshot.orders.filter { $0.bankID == lot.id }
                                let held = orders.reduce(0) { $0 + ($1.sell ? -$1.filled : $1.filled) }
                                Text("Owned units: \(held) · Unresolved orders: \(orders.filter { !AccountIDBank.terminal.contains($0.status) }.count)").font(.caption)
                                if !lot.reason.isEmpty { Text(lot.reason).font(.caption) }
                            }
                        }
                        Text("IDs and source identities are retained permanently. Timeouts and pending cancellations keep cash and owned-unit reservations.").font(.caption)
                    }
                }
            }
            .navigationTitle("Account ID bank")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .onAppear { refresh() }
        }
    }
}

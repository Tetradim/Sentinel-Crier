import SwiftUI
import UIKit

struct IntentConnectionForm: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage("connection-service-url") private var service = QuickConnection.defaultService
    @State private var pairing = ""
    @State private var invitation = ""
    @State private var shareLink = ""
    @State private var message = ""
    @State private var working = false
    @State private var receivers: [QuickConnection.Receiver] = []
    private func connect(host: Bool, newInvite: Bool = false) {
        working = true; message = ""
        Task { @MainActor in
            defer { working = false }
            do {
                if let link = try await model.quickConnect(host: host, service: service, invitation: invitation, newInvite: newInvite) { shareLink = link }
                if !host { invitation = "" }
                message = model.message
            } catch { message = error.localizedDescription }
        }
    }
    private func receiverAction(_ receiver: QuickConnection.Receiver? = nil) {
        working = true
        Task { @MainActor in
            defer { working = false }
            do {
                guard let pair = try IntentPairing.load() else { throw AlpacaError.invalid("Connect a host first.") }
                if let receiver { try await QuickConnection.revoke(receiver, pairing: pair) }
                receivers = try await QuickConnection.receivers(pair)
                message = receiver == nil ? "Receiver list refreshed." : "Receiver revoked. Existing broker orders still require reconciliation."
            } catch { message = error.localizedDescription }
        }
    }
    var body: some View {
        Section("Remote connection") {
            Button("Host") { connect(host: true) }.disabled(model.busy || working)
            SecureField("Invitation link or code (first connection)", text: $invitation)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .disabled(model.busy || working)
            Button("Receive") { connect(host: false) }.disabled(model.busy || working)
            if (try? IntentPairing.load())?.role == "host" {
                Button("Invite another receiver") { connect(host: true, newInvite: true) }.disabled(model.busy || working)
                Button("Refresh receivers") { receiverAction() }.disabled(working)
                ForEach(receivers) { receiver in
                    VStack(alignment: .leading) {
                        Text(receiver.id).font(.caption).textSelection(.enabled)
                        Text(receiver.revoked == 1 ? "Revoked" : "Connected receiver")
                        if receiver.revoked == 0 { Button("Revoke receiver", role: .destructive) { receiverAction(receiver) }.disabled(working) }
                    }
                }
            }
            if !shareLink.isEmpty {
                Text(shareLink).font(.caption).textSelection(.enabled)
                ShareLink("Share receiver invitation", item: shareLink)
                Button("Copy invitation") { UIPasteboard.general.string = shareLink }
                Text("Single use; expires after 10 minutes. Each additional receiver needs a new invitation.").font(.caption)
            }
            Text(model.lifecycle).font(.footnote)
            Button("Archive resolved channel and change connection", role: .destructive) {
                do { try model.changeChannel(); shareLink = ""; receivers = []; message = model.message }
                catch { message = error.localizedDescription }
            }.disabled(model.busy || working || model.account != nil)
            Text(message).font(.footnote)
            Text("Pair once; use Host or Receive to reconnect. Each device uses its own Alpaca keys. Keep this app open while following; iOS suspends background networking.").font(.caption)
            DisclosureGroup("Advanced connection setup") {
                TextField("HTTPS connection service URL", text: $service)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    .disabled(model.busy || working)
                Text("A hosted connection service is required. A receiver invitation link supplies its address automatically.").font(.caption)
                SecureField("Paste intent pairing JSON", text: $pairing).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Save host / follower pairing") {
                    do {
                        guard try IntentPairing.load() == nil else { throw AlpacaError.invalid("A pairing is already saved. Preserve its pinned journal; use Host or Receive to reconnect.") }
                        let value = try IntentPairing.decode(pairing)
                        guard value.environment == model.environment else { throw AlpacaError.invalid("Select the pairing's broker environment first.") }
                        try value.save(); MirrorPairing.remove(); pairing = ""; message = "Pairing saved. Press Host or Receive to activate."
                    } catch { message = error.localizedDescription }
                }.disabled(model.account != nil || model.busy || working)
            }
            if let intent = model.intent { IntentSettingsView(controller: intent) }
        }
    }
}
struct IntentSettingsView: View {
    @ObservedObject var controller: IntentController
    @State private var preferences = IntentPreferences()
    @State private var selectedPolicy = false
    @State private var policy = IntentExecutionPolicy()
    @State private var fixed = 1; @State private var ratio = 5000
    @State private var budget = "100"; @State private var notional = ""
    @State private var timed = false; @State private var timeout = 60
    @State private var message = ""
    var body: some View {
        VStack(alignment: .leading) {
            Toggle("Pause new follower entries", isOn: $preferences.paused)
            Picker("Follower pricing", selection: $preferences.mode) {
                Text("Exact source limit").tag("exact_limit")
                Text("Market (unbounded price)").tag("market")
                Text("Bounded limit").tag("bounded_limit")
            }
            Stepper("Slippage: \(preferences.maxSlippageBps) bps", value: $preferences.maxSlippageBps, in: 0...1000)
            TextField("Maximum absolute slippage", text: $preferences.maxSlippageAmount).keyboardType(.decimalPad)
            Stepper("Entry submit age: \(preferences.maxAgeSeconds)s", value: $preferences.maxAgeSeconds, in: 1...30)
            Stepper("Source quantity cap: \(preferences.maxQuantity)", value: $preferences.maxQuantity, in: 1...1000)
            Toggle("Select an advanced follower policy", isOn: $selectedPolicy)
            if selectedPolicy {
                Picker("Entry sizing", selection: $policy.mode) {
                    Text("Source quantity").tag("source"); Text("Fixed quantity").tag("fixed")
                    Text("Source ratio").tag("ratio"); Text("USD premium budget").tag("budget")
                }
                if policy.mode == "fixed" { Stepper("Fixed units: \(fixed)", value: $fixed, in: 1...1000) }
                if policy.mode == "ratio" { Stepper("Ratio: \(ratio) bps", value: $ratio, in: 1...10000) }
                if policy.mode == "budget" { TextField("USD entry budget", text: $budget).keyboardType(.decimalPad) }
                Stepper("Pinned source cap: \(policy.max_source_quantity)", value: $policy.max_source_quantity, in: 1...1000)
                Stepper("Local target cap: \(policy.max_local_quantity)", value: $policy.max_local_quantity, in: 1...1000)
                TextField("Optional maximum entry premium (USD)", text: $notional).keyboardType(.decimalPad)
                Picker("Exit sizing", selection: $policy.exit_mode) {
                    Text("Requested source units").tag("requested")
                    Text("Proportional source intent").tag("proportional")
                    Text("Close tracked local units").tag("close_tracked")
                }
                Text("Proportional exits use the sum of distinct source exit instructions against the last source entry target. They do not establish source fills and can differ when brokers fill or reject differently. Close tracked explicitly closes all tracked local units.").font(.caption)
                Toggle("Cancel timed entry remainder", isOn: $timed)
                if timed { Stepper("Entry timer: \(timeout)s", value: $timeout, in: 1...86400) }
                Text("Timed buys cancel on restart/reconnect after reconciliation; racing fills remain holdings. Suspension or network loss can delay cancellation. Policies require a verified USD account and standard US instruments.").font(.caption)
            }
            Text("The source cap rejects larger instructions. Selected policies affect new follower trade IDs only; existing trades keep their saved policy. Host quantities are unchanged. Policy edits must be saved with entries paused, then resumed separately.").font(.footnote)
            Text("Entry age is checked before submission. Day orders may remain working afterward. Pausing new entries leaves cancel and exit instructions active.").font(.footnote)
            Button("Apply follower settings") {
                do {
                    var next = preferences
                    var chosen = policy
                    chosen.fixed_quantity = chosen.mode == "fixed" ? fixed : nil
                    chosen.ratio_bps = chosen.mode == "ratio" ? ratio : nil
                    chosen.budget = chosen.mode == "budget" ? budget : nil
                    chosen.max_entry_notional = notional.isEmpty ? nil : notional
                    chosen.entry_timeout_seconds = timed ? timeout : nil
                    next.execution_policy = selectedPolicy ? chosen : nil
                    try controller.settings(next); preferences = next; message = "Saved."
                } catch { message = error.localizedDescription }
            }
            Text(controller.message).font(.footnote)
            Text("Unresolved tracked trades: \(controller.state.unresolved.count) • queued relay events: \(controller.state.outgoing.count)").font(.caption)
            ForEach(controller.state.unresolved, id: \.self) { id in Text(id).font(.caption).textSelection(.enabled) }
            if let records = controller.state.quarantine, !records.isEmpty {
                DisclosureGroup("Quarantined relay records (\(records.count))") {
                    ForEach(Array(records.enumerated()), id: \.offset) { _, record in
                        Text("Cursor \(record.cursor): \(record.reason)").font(.caption)
                    }
                }
            }
            Text(message).font(.footnote)
        }.onAppear {
            preferences = controller.state.preferences
            selectedPolicy = preferences.execution_policy != nil
            policy = preferences.execution_policy ?? IntentExecutionPolicy()
            fixed = policy.fixed_quantity ?? 1; ratio = policy.ratio_bps ?? 5000
            budget = policy.budget ?? "100"; notional = policy.max_entry_notional ?? ""
            timed = policy.entry_timeout_seconds != nil; timeout = policy.entry_timeout_seconds ?? 60
        }
    }
}
struct IntentTradesView: View {
    @ObservedObject var controller: IntentController
    var body: some View {
        Section("Tracked intent trades") {
            ForEach(controller.state.trades.keys.sorted(), id: \.self) { id in
                if let trade = controller.state.trades[id], let event = trade.desired {
                    IntentTradeRow(controller: controller, tradeID: id, event: event, owned: trade.owned)
                }
            }
        }
    }
}
struct IntentTradeRow: View {
    @ObservedObject var controller: IntentController
    let tradeID: String; let event: IntentEvent; let owned: Int
    @State private var quantity = 1
    @State private var price = ""
    @State private var message = ""
    private func send(_ action: String) {
        do { _ = try controller.host(symbol: event.symbol, asset: event.asset, quantity: quantity, price: price, tradeID: tradeID, action: action); message = "\(action.capitalized) journaled." }
        catch { message = error.localizedDescription }
    }
    var body: some View {
        VStack(alignment: .leading) {
            Text("\(event.symbol) • \(event.action) • owned \(owned)")
            Text(tradeID).font(.caption).textSelection(.enabled)
            if let trade = controller.state.trades[tradeID], let plan = trade.entryPlans?[event.event_id] {
                Text("Saved local target: \(plan.target) • cumulative bought: \(trade.bought) • limit: \(plan.price ?? "market") USD").font(.caption)
            }
            if let refusal = controller.state.trades[tradeID]?.policyRefusals?[event.event_id] { Text(refusal).font(.caption) }
            if controller.state.trades[tradeID]?.entryClosed == true { Text("Entry phase closed by timer; tracked fills retained.").font(.caption) }
            NavigationLink("Execution diagnostics") { IntentDiagnosticsView(controller: controller, tradeID: tradeID) }
            if controller.hosting {
                Stepper("Target / exit quantity: \(quantity)", value: $quantity, in: 1...1000)
                TextField("Limit price", text: $price).keyboardType(.decimalPad)
                Button("Replace remaining entry") { send("replace") }
                Button("Cancel entry remainder", role: .destructive) { send("cancel") }
                Button("Exit owned holdings", role: .destructive) { send("exit") }
            }
            Text(message).font(.caption)
        }.onAppear { quantity = event.quantity; price = event.limit_price }
    }
}

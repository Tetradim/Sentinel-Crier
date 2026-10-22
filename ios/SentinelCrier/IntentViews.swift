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
    var body: some View {
        Section("Remote connection") {
            Button("Host") { connect(host: true) }.disabled(model.busy || working)
            SecureField("Invitation link or code (first connection)", text: $invitation)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .disabled(model.busy || working)
            Button("Receive") { connect(host: false) }.disabled(model.busy || working)
            if (try? IntentPairing.load())?.role == "host" {
                Button("Invite another receiver") { connect(host: true, newInvite: true) }.disabled(model.busy || working)
            }
            if !shareLink.isEmpty {
                Text(shareLink).font(.caption).textSelection(.enabled)
                ShareLink("Share receiver invitation", item: shareLink)
                Button("Copy invitation") { UIPasteboard.general.string = shareLink }
                Text("Single use; expires after 10 minutes. Each additional receiver needs a new invitation.").font(.caption)
            }
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
            Stepper("Maximum age: \(preferences.maxAgeSeconds)s", value: $preferences.maxAgeSeconds, in: 1...30)
            Stepper("Maximum quantity: \(preferences.maxQuantity)", value: $preferences.maxQuantity, in: 1...1000)
            Button("Apply follower settings") { do { try controller.settings(preferences); message = "Saved." } catch { message = error.localizedDescription } }
            Text(controller.message).font(.footnote)
            Text(message).font(.footnote)
        }.onAppear { preferences = controller.state.preferences }
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

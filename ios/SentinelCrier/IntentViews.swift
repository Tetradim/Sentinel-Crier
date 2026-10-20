import SwiftUI

struct IntentConnectionForm: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var pairing = ""
    @State private var message = ""
    var body: some View {
        Section("Submission-time mirroring") {
            SecureField("Paste intent pairing JSON", text: $pairing).textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Save host / follower pairing") {
                do { try IntentPairing.decode(pairing).save(); MirrorPairing.remove(); pairing = ""; message = "Pairing saved. Reconnect Alpaca to activate." }
                catch { message = error.localizedDescription }
            }.disabled(model.account != nil)
            Text(message).font(.footnote)
            Text("Each device uses its own Alpaca keys. Keep this app open while following; iOS suspends background networking. Disconnect Alpaca to edit pairing.").font(.caption)
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

import SwiftUI

struct AlpacaConnectionForm: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var key = ""
    @State private var secret = ""
    var body: some View {
        Section("Alpaca personal Trading API") {
            Picker("Environment", selection: $model.environment) {
                Text("Paper • simulated funds").tag(AlpacaEnvironment.paper)
                Text("Live • real money").tag(AlpacaEnvironment.live)
            }.disabled(model.account != nil || model.busy)
            Text(model.environment == .paper
                 ? "Paper uses simulated funds. Use API keys from your Alpaca paper account."
                 : "Live orders use real money. Use API keys from your Alpaca live account; every manual order requires final confirmation.")
                .font(.footnote)
            Text("Keep Crier open for monitoring, following trades and Discord delivery. These pause when iOS suspends the app.")
                .font(.footnote)
            SecureField("API key ID", text: $key).textInputAutocapitalization(.never).autocorrectionDisabled()
            SecureField("API secret", text: $secret).textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Save & connect (or use saved keys)") { Task { await model.connect(key: key, secret: secret); key = ""; secret = "" } }.disabled(model.busy)
            if model.account != nil {
                Button("Disconnect") { model.disconnect() }.disabled(model.busy)
            }
            Button("Remove this environment’s credentials", role: .destructive) { model.disconnect(removeCredentials: true) }.disabled(model.busy)
            Text(model.message).font(.footnote)
            Text("Webull Connect approval pending. Tradier is not integrated. No brokerage password is requested.").font(.footnote).foregroundStyle(.secondary)
        }
        if model.purpose == .trade || model.purpose == .follow {
            IntentConnectionForm()
            if model.legacyRoute && (try? model.savedPairing()) == nil { MirrorConnectionForm() }
        }
    }
}

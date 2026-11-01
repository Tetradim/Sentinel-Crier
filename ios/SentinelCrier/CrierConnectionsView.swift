import SwiftUI

struct CrierConnectionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var webhook = ""
    @State private var configured = StandaloneConfiguration.webhook() != nil
    @State private var feedback: String?

    var body: some View {
        Form {
            AlpacaConnectionForm()
            Section("Trading") {
                NavigationLink("Supported trading and safeguards", destination: CrierSettingsView())
            }
            Section("Discord webhook") {
                SecureField("Discord webhook URL", text: $webhook)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save webhook") {
                    let raw = webhook.trimmingCharacters(in: .whitespacesAndNewlines)
                    webhook = ""
                    Task { @MainActor in
                        await model.saveDiscordWebhook(raw)
                        configured = StandaloneConfiguration.webhook() != nil
                        feedback = model.message
                    }
                }
                Text(configured ? "Configured" : "Not configured")
                    .foregroundStyle(configured ? .green : .secondary)
                Button("Remove webhook", role: .destructive) {
                    Task { @MainActor in
                        await model.saveDiscordWebhook(nil)
                        configured = StandaloneConfiguration.webhook() != nil
                        feedback = model.message
                    }
                }
                Text("Connect Alpaca and save a webhook to publish new broker fills to Discord while Crier is open. The first connection starts from a saved baseline; earlier fills are not posted.").font(.footnote)
                Text("Deliver or close outstanding alerts before changing destination. Closing keeps fill evidence in the journal.").font(.caption)
                if let feedback { Text(feedback).font(.footnote) }
            }.disabled(!model.legacyRoute)
        }
        .navigationTitle("Connections")
    }
}

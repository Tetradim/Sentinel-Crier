import SwiftUI

enum GuidedPurpose: String, CaseIterable, Identifiable {
    case alerts, trade, follow
    var id: String { rawValue }
    var title: String {
        switch self { case .alerts: return "Alerts only"; case .trade: return "Trade / share"; case .follow: return "Follow trades" }
    }
}

/// Network evidence and delivery permission deliberately never persist.
struct GuidedReadiness {
    var verified = false
    var previewed = false
    var testResult: String?
    var deliveryEnabled = false
    mutating func invalidate() { self = Self() }
}

struct GuidedSetupView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    var body: some View {
        NavigationStack {
            Form {
                Section("Optional practice and support") {
                    NavigationLink("Optional paper practice", destination: PracticeGuideView())
                        .accessibilityIdentifier("open-practice-guide")
                }
                Section("Account overview") {
                    NavigationLink("Connection health and recovery", destination: NativeHealthView())
                    NavigationLink("Provider connections and Crier sign-in", destination: ProviderConnectionsView())
                    NavigationLink("Account balances and saved positions", destination: BrokerageOverview())
                }
                Section("1 · Choose your purpose") {
                    Picker("Purpose", selection: Binding(get: { model.purpose }, set: { model.selectPurpose($0) })) {
                        Text("Choose a purpose").tag(Optional<GuidedPurpose>.none)
                        ForEach(GuidedPurpose.allCases) { Text($0.title).tag(Optional($0)) }
                    }.disabled(model.busy || model.account != nil)
                    Text("Disconnect before changing purpose. Saved accounts, orders, fills and channel journals are retained.").font(.caption)
                }
                if model.purpose != nil {
                    AlpacaConnectionForm()
                    Section("2 · Discord delivery") {
                        Text(model.readiness.verified ? "Account verified this session" : "Verify your account using Connect. Saved keys are reusable, not connection evidence.")
                        NavigationLink("Configure destination, preview and test", destination: CrierConnectionsView())
                        NavigationLink("Preview, test and enable delivery", destination: CrierExecutionsView())
                        Text("Preview, a synthetic test acknowledgement and permission to publish fills are separate steps. A test is optional; it never authorizes trading.").font(.footnote)
                    }
                }
                Section("Foreground operation") {
                    Text("Keep Crier open and unlocked. iOS suspension stops monitoring and following. Returning reconciles a connected account; explicitly re-enable Discord delivery. On restart, reconnect using saved keys; saved configuration does not resume delivery permission.")
                    Text(model.lifecycle).font(.caption)
                }
                Section("Advanced and recovery") {
                    NavigationLink("Saved positions and account", destination: BrokerageOverview())
                    NavigationLink("Orders and tracked trade recovery", destination: AlpacaTradingView())
                }
            }.navigationTitle("Home and setup")
        }
    }
}

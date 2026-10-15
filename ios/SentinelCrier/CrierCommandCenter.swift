import SwiftUI
import ReplayKit
import UIKit

@MainActor
final class StandaloneDashboard: ObservableObject {
    @Published var records: [StandaloneAlertStore.Record] = []
    @Published var enabled = StandaloneConfiguration.enabled
    @Published var configured = StandaloneConfiguration.webhook() != nil
    @Published var message: String?
    @Published var broadcast = "Not active"

    func refresh() {
        records = StandaloneAlertStore()?.records() ?? []
        enabled = StandaloneConfiguration.enabled
        configured = StandaloneConfiguration.webhook() != nil
        let defaults = UserDefaults(suiteName: StandaloneConfiguration.group)
        let age = Date().timeIntervalSince1970 - (defaults?.double(forKey: "broadcastHeartbeatAt") ?? 0)
        let state = defaults?.string(forKey: "broadcastState") ?? ""
        broadcast = state == "active" && age >= 0 && age < 12 ? "Recently active" :
            (state == "paused" && age >= 0 && age < 60 ? "Paused" : "Not active")
    }

    func setEnabled(_ value: Bool) {
        StandaloneConfiguration.setEnabled(value)
        refresh()
    }

    func save(_ webhook: String) {
        if StandaloneConfiguration.saveWebhook(webhook) {
            message = "Webhook securely saved on this iPhone."
        } else {
            message = "Invalid Discord webhook or Keychain unavailable. Check app signing."
        }
        refresh()
    }

    func clear() {
        StandaloneConfiguration.clear()
        message = "Discord delivery disabled and webhook deleted."
        refresh()
    }

    func retryPending() async {
        await StandaloneAlertStore()?.sendPending()
        refresh()
    }
}

struct CrierCommandCenter: View {
    @StateObject private var model = StandaloneDashboard()
    @State private var webhook = ""
    @State private var showDisclosure = false

    var body: some View {
        TabView {
            NavigationStack { dashboard }
                .tabItem { Label("Dashboard", systemImage: "house.fill") }
            LiveTradingHome()
                .tabItem { Label("Trade", systemImage: "chart.line.uptrend.xyaxis") }
            NavigationStack { activity }
                .tabItem { Label("Activity", systemImage: "list.bullet.rectangle") }
            NavigationStack { alerts }
                .tabItem { Label("Alerts", systemImage: "bell.badge") }
            NavigationStack { connections }
                .tabItem { Label("Connections", systemImage: "link") }
            NavigationStack { settings }
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
        .preferredColorScheme(.dark)
        .task { model.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            model.refresh()
        }
    }

    private var dashboard: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Standalone iPhone monitoring").font(.title2.bold())
                Label("No PC or Crier server required", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text("Screen observation: \(model.broadcast)")
                Text("Discord: \(model.configured ? "Configured" : "Not configured")")
                Text("Candidate alerts: \(model.enabled ? "Enabled" : "Disabled")")
                Text("Start monitoring while Webull is visible. iOS requires your permission for each screen broadcast.")
                    .font(.footnote).foregroundStyle(.secondary)
                ReplayKitPicker().frame(height: 56)
                Text("Recent observations").font(.headline)
                if model.records.isEmpty {
                    Text("No screen observations yet.").foregroundStyle(.secondary)
                }
                ForEach(model.records.prefix(5)) { row($0) }
                Button("Refresh") { model.refresh() }
            }.padding()
        }.navigationTitle("Sentinel Crier")
            .refreshable { model.refresh() }
    }

    private func row(_ record: StandaloneAlertStore.Record) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(record.evidence.symbol) \(record.evidence.expiration) \(record.evidence.strike)\(record.evidence.right)")
                .font(.headline)
            Text("\(record.evidence.side) \(record.evidence.quantity) @ $\(record.evidence.fillPrice)")
            Text("Unverified OCR candidate · \(record.state.capitalized)")
                .font(.caption).foregroundStyle(.orange)
            Text(record.note).font(.caption2).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
            .background(.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
    }

    private var activity: some View {
        List {
            Section("On-device observations — not broker-verified") {
                if model.records.isEmpty { Text("No observations.") }
                ForEach(model.records) { row($0) }
            }
        }.navigationTitle("Activity").refreshable { model.refresh() }
    }

    private var alerts: some View {
        Form {
            Section("Discord candidate alerts") {
                Toggle("Send unverified OCR observations", isOn: Binding(
                    get: { model.enabled },
                    set: { model.setEnabled($0) }
                )).disabled(!model.configured)
                Text("Alerts are clearly marked UNVERIFIED. Screen OCR is not proof of a broker execution.")
                    .font(.footnote)
                Button("Retry pending alerts") { Task { await model.retryPending() } }
                    .disabled(!model.enabled || !model.configured)
                Text("Uncertain deliveries are never retried automatically, to avoid duplicate Discord posts.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.navigationTitle("Alerts")
    }

    private var connections: some View {
        Form {
            Section("Discord webhook — no server required") {
                SecureField("Paste Discord webhook URL", text: $webhook)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save webhook on iPhone") {
                    model.save(webhook.trimmingCharacters(in: .whitespacesAndNewlines))
                    webhook = ""
                }
                Text(model.configured ? "Webhook securely configured" : "Webhook not configured")
                    .foregroundStyle(model.configured ? .green : .orange)
                Button("Remove webhook", role: .destructive) { model.clear() }
                if let message = model.message { Text(message).font(.caption) }
                Text("Create a webhook in your Discord server's channel settings. The URL is a secret; do not share it.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Screen capture") {
                ReplayKitPicker().frame(height: 56)
                Text("You must explicitly start broadcasting when you want Webull monitored.")
                    .font(.footnote)
            }
        }.navigationTitle("Connections")
    }

    private var settings: some View {
        Form {
            Section("Privacy and reliability") {
                Text("No PC, backend URL, brokerage password, or remote Crier server is required.")
                Text("Only structured observations are stored locally. Screenshots and raw OCR text are not retained.")
                Text("Repeated identical receipts may be suppressed to avoid duplicate alerts.")
                Text("iOS can stop the broadcast extension; this is not always-on background monitoring.")
            }
            Section("Local history") {
                Text("\(model.records.count) observations (up to 250 retained)")
                Text("\(model.records.filter { $0.state == "uncertain" }.count) uncertain deliveries")
                if let failed = UserDefaults(suiteName: StandaloneConfiguration.group)?
                    .double(forKey: "standaloneWriteFailureAt"), failed > 0 {
                    Text("A local storage write failed at \(Date(timeIntervalSince1970: failed).formatted()).")
                        .foregroundStyle(.red)
                }
            }
            Section("About") {
                Text("Sentinel Crier · Standalone iPhone beta")
                Text("Candidate alerts are not broker-verified fills.")
                    .foregroundStyle(.orange)
            }
        }.navigationTitle("Settings")
    }
}

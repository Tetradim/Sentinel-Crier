import SwiftUI

/// Original native SwiftUI shell: five primary tabs, with account settings
/// available from Home instead of consuming a permanent tab.
struct CrierCommandCenter: View {
    @StateObject private var model = AlpacaWorkspace()
    @StateObject private var connections = ProviderConnections()
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        TabView {
            GuidedSetupView()
                .tabItem { Label("Home", systemImage: "house") }
            CrierMarketsView()
                .tabItem { Label("Markets", systemImage: "chart.xyaxis.line") }
            if model.purpose == .trade || model.purpose == .follow {
                AlpacaTradingView()
                    .tabItem { Label(model.purpose == .follow ? "Follow" : "Trade", systemImage: "arrow.left.arrow.right") }
            }
            CrierPositionsView()
                .tabItem { Label("Positions", systemImage: "square.stack.3d.up") }
            CrierExecutionsView()
                .tabItem { Label("Alerts", systemImage: "bell") }
        }
        .environmentObject(model)
        .environmentObject(connections)
        .onOpenURL { url in
            Task { await connections.receive(url, environment: model.environment, purpose: model.purpose == .alerts ? "alerts" : "trade") }
        }
        .preferredColorScheme(.dark)
        .task(id: scenePhase) {
            connections.suspend(scenePhase != .active)
            await model.sceneActive(scenePhase == .active)
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await model.refresh()
                let paired = (try? MirrorPairing.load()) != nil
                do { try await Task.sleep(nanoseconds: paired ? 2_000_000_000 : 15_000_000_000) } catch { return }
            }
        }
    }
}

struct CrierPositionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    var body: some View {
        NavigationStack {
            List {
                Section("\(model.environment.rawValue.uppercased()) positions") {
                    if model.positions.isEmpty { Text("No positions loaded. Connect or refresh the account.") }
                    ForEach(model.positions) { position in
                        VStack(alignment: .leading) {
                            Text(position.symbol).font(.headline)
                            Text("Quantity: \(position.qty) • average $\(position.avg_entry_price)")
                            if let value = position.market_value { Text("Market value: $\(value)") }
                        }
                    }
                }
                Text(model.message).font(.footnote)
            }.navigationTitle("Positions").refreshable { await model.refresh() }
        }
    }
}
struct CrierExecutionsView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @AppStorage("discordFillStyle") private var style = "homebrew"
    @State private var settings = DiscordAlertSettings.load()
    @State private var feedback = ""
    @State private var retryEntry: AlpacaJournal.Delivery?
    @State private var closeEntry: AlpacaJournal.Delivery?
    var body: some View {
        NavigationStack {
            List {
                Section("Discord fill format") {
                    Picker("Format", selection: $style) {
                        Text("Homebrew Markdown").tag("homebrew")
                        Text("Plain text").tag("plain")
                        Text("Card").tag("card")
                    }
                    TextField("Template", text: $settings.template)
                    Text("Fields: {side}, {quantity}, {symbol}, {price}, {environment}").font(.caption)
                    Toggle("Include broker time", isOn: $settings.showTime)
                    Toggle("Include delivery reference", isOn: $settings.showReference)
                    Text("Synthetic preview · sample data, no broker execution").font(.caption)
                    Text(settings.render(DiscordAlertSettings.preview)).font(.caption).textSelection(.enabled)
                    Button("Save template and fields") {
                        do { try settings.save(); model.discordConfigurationChanged(); feedback = "Alert settings saved. Preview again before enabling delivery." } catch { feedback = error.localizedDescription }
                    }
                    Button("Preview current destination") {
                        do { try settings.save(); model.discordConfigurationChanged(); model.previewDiscord() }
                        catch { feedback = error.localizedDescription }
                    }.disabled(model.busy)
                    Text(model.readiness.previewed ? "Preview reviewed for this account and destination" : "Preview not reviewed for the current connection").font(.caption)
                    Button("Send synthetic test message") { Task { await model.sendDiscordTest() } }
                        .disabled(model.busy || !model.readiness.previewed)
                    Text(model.readiness.testResult ?? "No confirmed test this session. Test delivery is optional.").font(.caption)
                    Toggle("Publish verified broker fills", isOn: Binding(get: { model.readiness.deliveryEnabled }, set: { model.enableDiscordDelivery($0) }))
                        .disabled(model.busy || !model.readiness.previewed)
                    Text(feedback).font(.footnote)
                    Text("Only broker FILL activities are published. First connection sets a baseline; earlier history is not posted. Monitoring runs while this app is active. Uncertain deliveries need manual Discord verification and are never automatically resent.").font(.footnote)
                }
                Section("\(model.environment.rawValue.uppercased()) verified fills") {
                    ForEach(model.deliveries.reversed()) { entry in
                        VStack(alignment: .leading) {
                            Text("\(entry.fill.side.uppercased()) \(entry.fill.qty) \(entry.fill.symbol) @ $\(entry.fill.price)")
                            Text(entry.fill.transaction_time).font(.caption)
                            Text("Discord: \(entry.state)").font(.caption)
                            Text(entry.fill.id).font(.caption).textSelection(.enabled)
                            if let retry = entry.retryAfter { Text("Retry after: \(retry.formatted())").font(.caption) }
                            if entry.state == "pending" || entry.state == "uncertain" || entry.state.hasPrefix("rejected") {
                                Button("Retry delivery") {
                                    if entry.state == "uncertain" { retryEntry = entry }
                                    else { Task { await model.retryDiscord(entry.id, acknowledgeDuplicateRisk: false) } }
                                }.disabled(model.busy)
                                Button("Close alert without another post", role: .destructive) { closeEntry = entry }.disabled(model.busy)
                            }
                        }
                    }
                }
                Text(model.message).font(.footnote)
            }.onChange(of: style) { _ in model.discordConfigurationChanged() }
            .onChange(of: settings.template) { _ in model.discordConfigurationChanged() }
            .onChange(of: settings.showTime) { _ in model.discordConfigurationChanged() }
            .onChange(of: settings.showReference) { _ in model.discordConfigurationChanged() }
            .navigationTitle("Alerts").refreshable { await model.refresh() }
            .alert("Retry uncertain delivery?", isPresented: Binding(get: { retryEntry != nil }, set: { if !$0 { retryEntry = nil } })) {
                Button("Verified Discord; retry", role: .destructive) {
                    if let entry = retryEntry { Task { await model.retryDiscord(entry.id, acknowledgeDuplicateRisk: true) } }
                    retryEntry = nil
                }
                Button("Cancel", role: .cancel) { retryEntry = nil }
            } message: { Text("Check Discord for this fill first. The prior request may have succeeded; retry can create a duplicate.") }
            .alert("Close this alert?", isPresented: Binding(get: { closeEntry != nil }, set: { if !$0 { closeEntry = nil } })) {
                Button("Close without posting", role: .destructive) {
                    if let entry = closeEntry { Task { await model.closeDiscord(entry.id) } }
                    closeEntry = nil
                }
                Button("Cancel", role: .cancel) { closeEntry = nil }
            } message: { Text("The fill evidence is retained. This alert will not be posted again; its delivery status records your decision.") }
        }
    }
}

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
            }
        }
        .navigationTitle("Connections")
    }
}

struct CrierSettingsView: View {
    var body: some View {
        Form {
            Section("Supported trading") {
                Label("Manual Alpaca day limit orders", systemImage: "hand.tap")
                Text("Buy whole shares or standard 100-share option contracts; sell existing long holdings. Options require level 2 permission in your Alpaca account. Enter your own limit price in Trade.")
                    .font(.footnote).foregroundStyle(.secondary)
                Label("Host or follow paired trades", systemImage: "link")
                Text("Set up a remote connection in Connections. Keep Crier open to follow trades and deliver fill alerts.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            Section("Execution safeguards") {
                Label("Final order confirmation required", systemImage: "checkmark.shield")
                Label("Broker order reconciliation required", systemImage: "arrow.triangle.2.circlepath")
                Text("Idempotency, broker permissions, authenticated execution evidence and audit logging are mandatory and cannot be disabled.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Trading capabilities")
    }
}

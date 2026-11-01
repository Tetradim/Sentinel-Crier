import SwiftUI

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

import SwiftUI
import ReplayKit

private enum CrierTheme {
    static let background = Color(red: 0.035, green: 0.07, blue: 0.11)
    static let surface = Color(red: 0.075, green: 0.12, blue: 0.18)
    static let blue = Color(red: 0.13, green: 0.58, blue: 0.98)
    static let green = Color(red: 0.25, green: 0.85, blue: 0.56)
    static let amber = Color(red: 1, green: 0.74, blue: 0.26)
}

struct CrierActivity: Decodable, Identifiable {
    let id: String
    let status: String
    let created: Double
    let fill: Fill
    struct Fill: Decodable {
        let contract: String?
        let side: String?
        let quantity: String?
        let price: String?
        let broker: String?
    }
}

struct CrierObservation: Decodable, Identifiable {
    let id: String
    let status: String
    let evidence: Evidence
    struct Evidence: Decodable {
        let symbol: String
        let side: String
        let quantity: Int
    }
}

struct CrierPreferences: Codable {
    var display_name = "Your trades"
    var format = "homebrew"
    var color = "#62d9ad"
    var timezone = "America/Chicago"
    var show_quantity = true
    var show_time = true
    var paused = false
}

@MainActor
final class CrierDashboardModel: ObservableObject {
    @Published var status: CrierStatusClient.Status?
    @Published var activity: [CrierActivity] = []
    @Published var observations: [CrierObservation] = []
    @Published var preferences = CrierPreferences()
    @Published var error: String?
    @Published var loading = false

    private func endpoint(_ path: String, method: String = "GET", body: Data? = nil) throws -> URLRequest {
        guard let raw = UserDefaults.standard.string(forKey: "crier.backendURL"),
              let url = URL(string: raw), url.scheme?.lowercased() == "https",
              url.host != nil, url.user == nil, url.password == nil,
              let token = CrierCredentials.load(), !token.isEmpty else {
            throw CrierStatusClient.ClientError.invalidURL
        }
        var request = URLRequest(url: url.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = 12
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        request.httpBody = body
        return request
    }

    private func fetch<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: endpoint(path))
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw CrierStatusClient.ClientError.invalidResponse
        }
        return try JSONDecoder().decode(type, from: data)
    }

    func refresh() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        do {
            let newStatus = try await fetch("api/status", as: CrierStatusClient.Status.self)
            let newActivity = try await fetch("api/history", as: [CrierActivity].self)
            let newObservations = try await fetch("api/screen-observations", as: [CrierObservation].self)
            let newPreferences = try await fetch("api/settings", as: CrierPreferences.self)
            status = newStatus
            activity = newActivity
            observations = newObservations
            preferences = newPreferences
            error = nil
        } catch {
            status = nil
            self.error = "Unable to refresh. Check your server connection and access token."
        }
    }

    func savePreferences() async {
        do {
            let body = try JSONEncoder().encode(preferences)
            let (data, response) = try await URLSession.shared.data(
                for: endpoint("api/settings", method: "PUT", body: body))
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw CrierStatusClient.ClientError.invalidResponse
            }
            preferences = try JSONDecoder().decode(CrierPreferences.self, from: data)
            error = nil
        } catch {
            error = "Could not save preferences. Check the connection and display name."
        }
    }
}

private struct CrierPanel<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline).foregroundStyle(.white)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CrierTheme.surface, in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct CrierMetric: View {
    let title: String
    let value: String
    let tint: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value).font(.title.bold()).foregroundStyle(tint)
            Text(title).font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(CrierTheme.surface, in: RoundedRectangle(cornerRadius: 14))
    }
}

struct CrierCommandCenter: View {
    @StateObject private var model = CrierDashboardModel()
    var body: some View {
        TabView {
            NavigationStack { dashboard }
                .tabItem { Label("Dashboard", systemImage: "house.fill") }
            NavigationStack { activity }
                .tabItem { Label("Activity", systemImage: "list.bullet.rectangle") }
            NavigationStack { alerts }
                .tabItem { Label("Alerts", systemImage: "bell.badge") }
            NavigationStack { connections }
                .tabItem { Label("Connections", systemImage: "link") }
            NavigationStack { settings }
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
        .tint(CrierTheme.blue)
        .preferredColorScheme(.dark)
        .task { await model.refresh() }
    }

    private var dashboard: some View {
        ScrollView {
            VStack(spacing: 14) {
                CrierPanel(title: "Monitoring overview") {
                    Label("Screen broadcasting requires explicit iPhone permission",
                          systemImage: "iphone.gen3.radiowaves.left.and.right")
                        .foregroundStyle(CrierTheme.amber)
                    Text("A configured upload key does not mean broadcasting is active.")
                        .font(.caption).foregroundStyle(.secondary)
                    ReplayKitPicker().frame(height: 54)
                }
                HStack(spacing: 9) {
                    CrierMetric(title: "Observations", value: "\(model.observations.count)", tint: CrierTheme.blue)
                    CrierMetric(title: "Delivered", value: "\(model.activity.filter { $0.status == "sent" }.count)", tint: CrierTheme.green)
                    CrierMetric(title: "Review", value: "\(model.observations.filter { $0.status == "pending_review" }.count)", tint: CrierTheme.amber)
                }
                CrierPanel(title: "Connection status") {
                    statusLine("Crier server", value: model.status == nil ? "Not verified" : "Online",
                               color: model.status == nil ? CrierTheme.amber : CrierTheme.green)
                    statusLine("Discord publisher",
                               value: model.status?.delivery_enabled == true ? "Enabled" : "Not enabled",
                               color: model.status?.delivery_enabled == true ? CrierTheme.green : CrierTheme.amber)
                    statusLine("Webull screen", value: "Broadcast state unverified", color: CrierTheme.amber)
                }
                CrierPanel(title: "Recent verified-fill activity") {
                    if model.activity.isEmpty {
                        Text("No verified fills in history.").foregroundStyle(.secondary)
                    }
                    ForEach(model.activity.prefix(4)) { item in activityRow(item) }
                }
                if let error = model.error {
                    Text(error).font(.footnote).foregroundStyle(CrierTheme.amber)
                }
            }.padding()
        }
        .background(CrierTheme.background)
        .navigationTitle("Sentinel Crier")
        .toolbar { Button { Task { await model.refresh() } } label: {
            Image(systemName: "arrow.clockwise")
        }.disabled(model.loading) }
        .refreshable { await model.refresh() }
    }

    private func statusLine(_ title: String, value: String, color: Color) -> some View {
        HStack {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(title)
            Spacer()
            Text(value).font(.caption).foregroundStyle(color)
        }
    }

    private func activityRow(_ item: CrierActivity) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(item.fill.contract ?? "Unknown contract").font(.subheadline.bold())
                Text("\(item.fill.side ?? "—") · \(item.fill.quantity ?? "—") @ \(item.fill.price ?? "—")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(item.status.capitalized).font(.caption.bold())
                .foregroundStyle(item.status == "sent" ? CrierTheme.green : CrierTheme.amber)
        }.padding(.vertical, 5)
    }

    private var activity: some View {
        List {
            Section("Verified-fill delivery history") {
                if model.activity.isEmpty { Text("No delivery records.").foregroundStyle(.secondary) }
                ForEach(model.activity) { activityRow($0) }
            }
            Section("Untrusted screen observations — never auto-published") {
                if model.observations.isEmpty { Text("No screen observations.").foregroundStyle(.secondary) }
                ForEach(model.observations) { item in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(item.evidence.symbol).font(.headline)
                            Text("\(item.evidence.side) · \(item.evidence.quantity) contracts").font(.caption)
                        }
                        Spacer()
                        Text("Pending review").font(.caption).foregroundStyle(CrierTheme.amber)
                    }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(CrierTheme.background)
        .navigationTitle("Activity")
        .refreshable { await model.refresh() }
    }

    private var alerts: some View {
        Form {
            Section("Message appearance") {
                TextField("Display name", text: $model.preferences.display_name)
                Picker("Format", selection: $model.preferences.format) {
                    Text("Homebrew Markdown").tag("homebrew")
                    Text("Discord rich card").tag("card")
                    Text("Plain text").tag("text")
                    Text("Echo BTO only").tag("echo")
                }
                Toggle("Show quantity", isOn: $model.preferences.show_quantity)
                Toggle("Show time", isOn: $model.preferences.show_time)
                Button("Save alert design") { Task { await model.savePreferences() } }
            }
            Section("Illustrative preview — not a real alert") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("🟢 SPY $600C · 10/16/2026").font(.headline)
                    Text("BUY · 4 contracts · Filled @ $1.25")
                    Text(model.preferences.display_name).foregroundStyle(.secondary)
                    Text("SAMPLE · NOT SENT").font(.caption.bold()).foregroundStyle(CrierTheme.amber)
                }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    .background(CrierTheme.surface, in: RoundedRectangle(cornerRadius: 12))
            }
            if let error = model.error { Text(error).foregroundStyle(CrierTheme.amber) }
        }.navigationTitle("Alert Designer")
    }

    private var connections: some View {
        ScrollView {
            VStack(spacing: 14) {
                CrierPanel(title: "Crier backend") {
                    statusLine("Connection", value: model.status == nil ? "Not verified" : "Online",
                               color: model.status == nil ? CrierTheme.amber : CrierTheme.green)
                }
                CrierPanel(title: "Discord") {
                    statusLine("Webhook", value: model.status?.discord_configured == true ? "Configured" : "Not configured",
                               color: model.status?.discord_configured == true ? CrierTheme.green : CrierTheme.amber)
                }
                CrierPanel(title: "Webull screen observation") {
                    Text("Screen OCR observations remain pending review and never automatically publish to Discord.")
                        .font(.footnote).foregroundStyle(.secondary)
                    ReplayKitPicker().frame(height: 54)
                }
                NavigationLink("Configure server and upload credentials") { SetupView() }
                    .buttonStyle(.borderedProminent)
            }.padding()
        }.background(CrierTheme.background).navigationTitle("Connections")
    }

    private var settings: some View {
        Form {
            Section("Monitoring") {
                Toggle("Pause Discord delivery", isOn: $model.preferences.paused)
                Text("Pausing delivery does not stop observation capture.")
                    .font(.caption).foregroundStyle(.secondary)
                Button("Save monitoring preference") { Task { await model.savePreferences() } }
            }
            Section("Privacy and credentials") {
                NavigationLink("Server credentials and screen upload") { SetupView() }
                Text("Disabling screen upload in Connections erases queued observations on this device.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("About") {
                Text("Sentinel Crier · Experimental iOS companion")
                Text("OCR observations are untrusted evidence, not verified executions.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.navigationTitle("Settings")
    }
}

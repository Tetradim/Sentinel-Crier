import SwiftUI
import ReplayKit

@main
struct SentinelCrierApp: App {
    var body: some Scene {
        WindowGroup { CrierCommandCenter() }
    }
}

struct SetupView: View {
    @AppStorage("crier.backendURL") private var backendURL = ""
    @State private var showHelp = false
    @State private var token = ""
    @State private var uploadToken = ""
    @State private var uploadMessage = "Screen upload not configured"
    @State private var connectionMessage = "Not connected"
    @State private var checkingConnection = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Welcome to Sentinel Crier") {
                    Text("Connect your Crier service, then start screen monitoring when you trade. Broker API monitoring, when configured on the server, continues independently.")
                }
                Section("1 · Connect") {
                    TextField("https://your-crier-server.example", text: $backendURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    SecureField("Crier access token", text: $token)
                    Button("Forget saved token", role: .destructive) {
                        CrierCredentials.clear()
                        token = ""
                        connectionMessage = "Saved token removed."
                    }
                    Button(checkingConnection ? "Checking…" : "Check connection") {
                        Task { await checkConnection() }
                    }
                    .disabled(checkingConnection)
                    Text(connectionMessage).font(.footnote)
                    Text("Use a private HTTPS Crier server. Never paste brokerage passwords or Discord webhooks here.")
                        .font(.footnote)
                }
                Section("2 · Configure Webull screen upload") {
                    SecureField("Dedicated screen upload token", text: $uploadToken)
                    Button("Enable secure screen upload") {
                        guard let url = URL(string: backendURL),
                              ScreenUploadConfiguration.configure(baseURL: url, token: uploadToken) else {
                            uploadMessage = "Unable to save upload configuration. Check HTTPS and signing entitlements."
                            return
                        }
                        uploadToken = ""
                        uploadMessage = "Screen upload configured. OCR observations are held for review."
                    }
                    Button("Disable screen upload", role: .destructive) {
                        ScreenUploadConfiguration.clear()
                        uploadToken = ""
                        uploadMessage = "Screen upload disabled."
                    }
                    Text(uploadMessage).font(.footnote)
                    Text("Use CRIER_SCREEN_UPLOAD_KEY, not your main Crier access token. Configure this on the server first.")
                        .font(.footnote)
                }
                Section("3 · Start screen monitoring") {
                    Text("iOS asks for your permission to share the screen. The broadcast extension must be bundled with this app and configured in Xcode.")
                    ReplayKitPicker()
                        .frame(height: 54)
                        .accessibilityLabel("Start screen monitoring")
                    Text("Only visible confirmations can be detected. An order preview is not a confirmed fill.")
                        .font(.footnote)
                }
                Section("4 · Check alerts") {
                    Text("Discord publishing requires an authenticated Crier backend. Screen capture alone does not send alerts.")
                    Button("How monitoring works") { showHelp = true }
                }
            }
            .navigationTitle("Sentinel Crier")
            .onAppear { token = CrierCredentials.load() ?? "" }
            .alert("Monitoring modes", isPresented: $showHelp) {
                Button("OK", role: .cancel) {}
            } message: {
                Text("API monitoring is hosted. Screen monitoring requires an active, user-authorized capture session. Neither method places trades.")
            }
        }
    }
    @MainActor
    private func checkConnection() async {
        guard let url = URL(string: backendURL) else {
            connectionMessage = "Enter a valid HTTPS server URL."
            return
        }
        checkingConnection = true
        defer { checkingConnection = false }
        do {
            let status = try await CrierStatusClient(baseURL: url, accessToken: token).status()
            guard CrierCredentials.save(token) else {
                connectionMessage = "Connected, but could not securely save the token."
                return
            }
            connectionMessage = status.delivery_enabled
                ? "Connected · Discord delivery enabled"
                : "Connected · preview mode"
        } catch {
            connectionMessage = "Connection failed. Check the server URL and access token."
        }
    }
}

struct ReplayKitPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: .zero)
        picker.preferredExtension = "com.tetradim.sentinelcrier.BroadcastUpload"
        picker.showsMicrophoneButton = false
        return picker
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}

import SwiftUI
import ReplayKit

@main
struct SentinelCrierApp: App {
    var body: some Scene {
        WindowGroup { CrierCommandCenter() }
    }
}

/// iOS requires a user-started ReplayKit broadcast; it cannot be enabled invisibly.
struct ReplayKitPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: .zero)
        picker.preferredExtension = "com.tetradim.sentinelcrier.BroadcastUpload"
        picker.showsMicrophoneButton = false
        return picker
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}

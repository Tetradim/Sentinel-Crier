import ReplayKit
import Vision
import CoreImage
import Foundation

/// Screen-only observation. This extension does not publish trades.
/// A completed-fill classifier and authenticated backend submission must be
/// implemented and validated before enabling customer-facing alerts.
final class SampleHandler: RPBroadcastSampleHandler {
    private let queue = DispatchQueue(label: "com.tetradim.crier.ocr")
    private var lastSampleAt: TimeInterval = 0
    private let interval: TimeInterval = 1.0
    private var busy = false

    override func broadcastStarted(withSetupInfo setupInfo: [String : NSObject]?) {
        lastSampleAt = 0
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastSampleAt >= interval, !busy else { return }
        lastSampleAt = now
        busy = true
        queue.async { [weak self] in
            defer { self?.busy = false }
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            do {
                try VNImageRequestHandler(cvPixelBuffer: pixelBuffer).perform([request])
                // Do not log or transmit recognized text: it can contain private account data.
                // A broker-specific confirmed-fill parser is required before alert emission.
                _ = request.results?.compactMap { $0.topCandidates(1).first?.string }
            } catch {
                // Capture must remain functional if one frame cannot be recognized.
            }
        }
    }
}

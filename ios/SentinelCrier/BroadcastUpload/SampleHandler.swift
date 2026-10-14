import ReplayKit
import Vision
import Foundation

/// User-authorized capture; OCR stays on-device. No automatic Discord publishing.
final class SampleHandler: RPBroadcastSampleHandler {
    // All throttling and dedup state is owned by this serial queue.
    private let queue = DispatchQueue(label: "com.tetradim.crier.ocr")
    private var lastSampleAt: TimeInterval = 0
    private let interval: TimeInterval = 1.0
    private let deduplicator = ScreenObservationDeduplicator()

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        queue.async { [weak self] in self?.lastSampleAt = 0 }
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer,
                                      with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        // Keep the frame alive while Vision runs asynchronously.
        CVPixelBufferRetain(pixelBuffer)
        queue.async { [weak self] in
            defer { CVPixelBufferRelease(pixelBuffer) }
            guard let self = self else { return }
            let now = ProcessInfo.processInfo.systemUptime
            guard now - self.lastSampleAt >= self.interval else { return }
            self.lastSampleAt = now

            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            do {
                try VNImageRequestHandler(cvPixelBuffer: pixelBuffer).perform([request])
                let lines = request.results?.compactMap { $0.topCandidates(1).first?.string } ?? []
                // No raw text, screenshots or brokerage credentials leave this extension.
                // Candidate detection is advisory until validated against actual Webull receipts.
                if case .candidate(let candidate) =
                    BrokerScreenTemplate(name: "webull").recognize(lines: lines) {
                    _ = self.deduplicator.shouldAccept(candidate)
                }
            } catch {
                // A single failed OCR frame must not terminate screen capture.
            }
        }
    }
}

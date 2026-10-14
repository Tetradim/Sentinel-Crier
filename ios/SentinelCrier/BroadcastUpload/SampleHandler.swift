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
    private let evidenceQueue = ScreenEvidenceQueue()
    private var flushInProgress = false
    // A single retained video buffer at most, even when Vision OCR is slow.
    private let frameGate = DispatchSemaphore(value: 1)
    private let shared = UserDefaults(suiteName: "group.com.tetradim.sentinelcrier")

    private func broadcastState(_ state: String) {
        shared?.set(state, forKey: "broadcastState")
        shared?.set(Date().timeIntervalSince1970, forKey: "broadcastHeartbeatAt")
    }

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        queue.async { [weak self] in
            self?.lastSampleAt = 0
            self?.deduplicator.reset()
            self?.broadcastState("active")
            self?.flushEvidence()
        }
    }

    override func broadcastPaused() {
        queue.async { [weak self] in
            self?.deduplicator.reset()
            self?.broadcastState("paused")
        }
    }

    override func broadcastResumed() {
        queue.async { [weak self] in
            self?.deduplicator.reset()
            self?.lastSampleAt = 0
            self?.broadcastState("active")
            self?.flushEvidence()
        }
    }

    override func broadcastFinished() {
        queue.async { [weak self] in
            self?.deduplicator.screenChanged()
            self?.lastSampleAt = 0
        }
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer,
                                      with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        // Drop incoming frames before retaining them in the OCR work queue.
        guard frameGate.wait(timeout: .now()) == .success else { return }
        queue.async { [weak self] in
            defer { self?.frameGate.signal() }
            guard let self = self,
                  let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
            let now = ProcessInfo.processInfo.systemUptime
            guard now - self.lastSampleAt >= self.interval else { return }
            self.lastSampleAt = now
            self.broadcastState("active")

            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            do {
                try VNImageRequestHandler(cvPixelBuffer: pixelBuffer).perform([request])
                let lines = request.results?.compactMap { $0.topCandidates(1).first?.string } ?? []
                // No raw text, screenshots or brokerage credentials leave this extension.
                // Candidate detection is advisory until validated against actual Webull receipts.
                let recognition = BrokerScreenTemplate(name: "webull").recognize(lines: lines)
                if case .candidate(let candidate) = recognition {
                    if ScreenUploadConfiguration.load() != nil && self.deduplicator.shouldAccept(candidate) {
                        self.evidenceQueue?.enqueue(ScreenEvidence(candidate: candidate))
                    }
                } else {
                    self.deduplicator.screenChanged()
                }
            } catch {
                // A single failed OCR frame must not terminate screen capture.
                self.deduplicator.screenChanged()
            }
            self.flushEvidence()
        }
    }

    /// Called only from the serial OCR queue.
    private func flushEvidence() {
        guard !flushInProgress, let evidenceQueue = evidenceQueue else { return }
        flushInProgress = true
        Task { [weak self] in
            await evidenceQueue.flush()
            self?.queue.async { [weak self] in self?.flushInProgress = false }
        }
    }
}

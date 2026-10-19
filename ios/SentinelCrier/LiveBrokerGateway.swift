import Foundation

/// Broker-neutral values returned by an authenticated live brokerage connection.
struct LiveAccount: Codable, Identifiable, Hashable {
    let brokerId: String
    let accountId: String
    let displayName: String
    let currency: String
    let buyingPower: Decimal?
    let equity: Decimal?
    var id: String { brokerId + ":" + accountId }
}

struct LiveOptionQuote: Codable, Identifiable, Hashable {
    let contract: LiveOptionContract
    let bid: Decimal?
    let ask: Decimal?
    let bidSize: Int?
    let askSize: Int?
    let quotedAt: Date
    var id: String { contract.brokerContractId }
}

struct LivePosition: Codable, Identifiable {
    let brokerId: String
    let accountId: String
    let instrumentId: String
    let description: String
    let quantity: Decimal
    let averagePrice: Decimal?
    let marketValue: Decimal?
    var id: String { brokerId + ":" + accountId + ":" + instrumentId }
}

struct LiveOrderPreview: Codable {
    let brokerId: String
    let accountId: String
    let clientOrderId: String
    let estimatedTotal: Decimal?
    let estimatedFees: Decimal?
    let buyingPowerEffect: Decimal?
    let warnings: [String]
    let previewedAt: Date
    let expiresAt: Date?

    func matches(_ request: LiveOrderRequest, now: Date = Date()) -> Bool {
        brokerId == request.brokerId && accountId == request.accountId &&
        clientOrderId == request.clientOrderId &&
        previewedAt <= now && (expiresAt == nil || expiresAt! > now)
    }
}

enum LiveOrderLifecycle: String, Codable {
    case awaitingConfirmation
    case submitting
    case accepted
    case partiallyFilled
    case filled
    case canceled
    case rejected
    case unknown // MUST reconcile before attempting any new submission
}

struct LiveOrderReceipt: Codable {
    let brokerId: String
    let accountId: String
    let clientOrderId: String
    let brokerOrderId: String?
    let status: LiveOrderLifecycle
    let receivedAt: Date
}

/// Capabilities are explicit: brokers without options, previews or authenticated
/// execution retrieval must not expose those operations as available.
protocol LiveBrokerGateway {
    func brokers() async throws -> [LiveBrokerDescriptor]
    func accounts(brokerId: String) async throws -> [LiveAccount]
    func positions(brokerId: String, accountId: String) async throws -> [LivePosition]
    func optionChain(brokerId: String, underlying: String, expiration: String) async throws -> [LiveOptionQuote]
    func preview(_ request: LiveOrderRequest) async throws -> LiveOrderPreview
    func submit(_ request: LiveOrderRequest) async throws -> LiveOrderReceipt
    func orderStatus(brokerId: String, accountId: String, clientOrderId: String) async throws -> LiveOrderReceipt
    func executions(brokerId: String, accountId: String, brokerOrderId: String) async throws -> [BrokerConfirmedExecution]
}

/// Local gate is intentionally fail-closed. The approved broker integration must
/// ALSO enforce confirmation, account authorization, and idempotency server-side.
actor LiveOrderConfirmationGate {
    private var activeOrderId: String?
    private var approvedRequest: LiveOrderRequest?
    private var approvedPreview: LiveOrderPreview?
    private var submissionStarted = false

    func begin(_ request: LiveOrderRequest, preview: LiveOrderPreview) throws {
        try request.validate()
        guard activeOrderId == nil, preview.matches(request) else {
            throw LiveOrderError.invalidOrder
        }
        approvedRequest = request
        approvedPreview = preview
        activeOrderId = request.clientOrderId
        submissionStarted = false
    }

    /// Call only in the explicit, customer-confirmed action handler.
    func submitConfirmed(_ request: LiveOrderRequest, via gateway: LiveBrokerGateway) async throws -> LiveOrderReceipt {
        guard activeOrderId == request.clientOrderId, approvedRequest == request,
              let preview = approvedPreview, preview.matches(request),
              Date().timeIntervalSince(preview.previewedAt) < 60, !submissionStarted else {
            throw LiveOrderError.invalidOrder
        }
        submissionStarted = true
        // Do not clear the guard on a timeout: submission may have succeeded.
        return try await gateway.submit(request)
    }

    func finishWithoutSubmission(clientOrderId: String) {
        guard activeOrderId == clientOrderId, !submissionStarted else { return }
        activeOrderId = nil
    }
}

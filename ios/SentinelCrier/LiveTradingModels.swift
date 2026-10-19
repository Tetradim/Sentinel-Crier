import Foundation

/// Contract for real-money brokerage integrations. No simulated order or account types.
enum LiveBrokerCapability: String, Codable, CaseIterable {
    case accounts, balances, positions, optionChains, optionOrders, stockOrders
    case orderPreview, orderCancellation, executionEvents
}

enum LiveBrokerConnectionState: String, Codable {
    case disconnected, authorizationRequired, connected, unavailable
}

struct LiveBrokerDescriptor: Identifiable, Codable {
    let id: String
    let displayName: String
    let state: LiveBrokerConnectionState
    let capabilities: Set<LiveBrokerCapability>
    let detail: String?

    func supports(_ capability: LiveBrokerCapability) -> Bool {
        state == .connected && capabilities.contains(capability)
    }
}

struct LiveOptionContract: Codable, Hashable {
    let brokerContractId: String
    let underlying: String
    let expiration: String
    let strike: Decimal
    let right: String
    let multiplier: Int
}

enum LiveOrderAction: String, Codable {
    case buyToOpen, sellToClose, sellToOpen, buyToClose
}

struct LiveOrderRequest: Codable, Equatable {
    let brokerId: String
    let accountId: String
    let contract: LiveOptionContract
    let action: LiveOrderAction
    let contracts: Int
    let limitPrice: Decimal
    let clientOrderId: String

    func validate() throws {
        guard !brokerId.isEmpty, !accountId.isEmpty,
              !contract.brokerContractId.isEmpty, !clientOrderId.isEmpty,
              contracts > 0, contract.multiplier > 0, limitPrice > 0,
              contract.right == "C" || contract.right == "P" else {
            throw LiveOrderError.invalidOrder
        }
    }
}

enum LiveOrderError: Error {
    case invalidOrder
    case authorizationRequired
    case unsupportedCapability
    case unavailable
}

/// Implementations must use official, approved broker endpoints and report
/// unknown submission outcomes without blindly resubmitting the order.
protocol LiveBrokerTrading {
    func connectedAccounts() async throws -> [LiveBrokerDescriptor]
    func submitConfirmedOrder(_ request: LiveOrderRequest) async throws -> String
    func reconcileOrder(brokerId: String, accountId: String, clientOrderId: String) async throws
}

/// Execution evidence must come from a broker, never from screen OCR or a submit acknowledgement.
struct BrokerConfirmedExecution: Codable, Hashable {
    let brokerId: String
    let accountId: String
    let brokerOrderId: String
    let executionId: String
    let contract: LiveOptionContract
    let action: LiveOrderAction
    let incrementalQuantity: Int
    let executionPrice: Decimal
    let executedAt: Date

    func validate() throws {
        guard !brokerId.isEmpty, !accountId.isEmpty,
              !brokerOrderId.isEmpty, !executionId.isEmpty,
              incrementalQuantity > 0, executionPrice > 0 else {
            throw LiveOrderError.invalidOrder
        }
    }

    var deduplicationKey: String {
        [brokerId, accountId, brokerOrderId, executionId].joined(separator: ":")
    }
}

import Foundation

/// One customer-authorized intent spanning several independently executing broker orders.
/// A group is never treated as atomically filled: each broker retains its own state.
struct MultiBrokerTradeGroup: Codable, Identifiable {
    let id: UUID
    let createdAt: Date
    let underlying: String
    let expiration: String
    let strike: Decimal
    let right: String
    let action: LiveOrderAction
    let quantityMode: MultiBrokerQuantityMode
    let requestedQuantity: Int
    let legs: [MultiBrokerTradeLeg]

    var totalRequested: Int { legs.reduce(0) { $0 + $1.requestedContracts } }
    var totalFilled: Int { legs.reduce(0) { $0 + $1.filledContracts } }
    var isComplete: Bool { legs.allSatisfy { $0.filledContracts == $0.requestedContracts } }
}

struct MultiBrokerTradeLeg: Codable, Identifiable {
    let brokerId: String
    let accountId: String
    let brokerContractId: String
    let clientOrderId: String
    let requestedContracts: Int
    let filledContracts: Int
    let status: LiveOrderLifecycle
    let averageFillPrice: Decimal?
    var id: String { brokerId + ":" + accountId + ":" + clientOrderId }
}

/// This is a planning artifact, not an order submission. Every account must
/// independently pass contract, permission, buying-power and preview checks.
struct MultiBrokerOrderPlan: Codable {
    let id: UUID
    let createdAt: Date
    let quantityMode: MultiBrokerQuantityMode
    let requests: [LiveOrderRequest]
    let previews: [LiveOrderPreview]

    var totalContracts: Int { requests.reduce(0) { $0 + $1.contracts } }

    func validate(now: Date = Date()) throws {
        guard !requests.isEmpty, requests.count == previews.count,
              Set(requests.map { $0.brokerId + ":" + $0.accountId }).count == requests.count,
              Set(requests.map(\.clientOrderId)).count == requests.count else {
            throw LiveOrderError.invalidOrder
        }
        for (request, preview) in zip(requests, previews) {
            try request.validate()
            guard preview.matches(request, now: now) else { throw LiveOrderError.invalidOrder }
        }
    }
}

enum MultiBrokerOrderPlanner {
    /// Broker-resolved contract IDs must be supplied for each account.
    static func prepare(
        allocations: [MultiBrokerAllocation],
        contractsByAccount: [String: LiveOptionContract],
        action: LiveOrderAction,
        limitPrice: Decimal,
        quantityMode: MultiBrokerQuantityMode
    ) throws -> [LiveOrderRequest] {
        guard !allocations.isEmpty, limitPrice > 0 else { throw LiveOrderError.invalidOrder }
        return try allocations.map { allocation in
            guard let contract = contractsByAccount[allocation.id] else {
                throw LiveOrderError.invalidOrder
            }
            let request = LiveOrderRequest(
                brokerId: allocation.brokerId,
                accountId: allocation.accountId,
                contract: contract,
                action: action,
                contracts: allocation.contracts,
                limitPrice: limitPrice,
                clientOrderId: UUID().uuidString)
            try request.validate()
            return request
        }
    }
}

/// Close-only sizing based on real broker positions, not the quantity originally
/// ordered. A broker holding fewer contracts cannot be instructed to close more.
enum MultiBrokerClosePlanner {
    static func validateClosingQuantities(
        allocations: [MultiBrokerAllocation],
        positionsByAccountAndContract: [String: Int],
        contractsByAccount: [String: LiveOptionContract]
    ) throws {
        guard !allocations.isEmpty else { throw LiveOrderError.invalidOrder }
        for allocation in allocations {
            guard let contract = contractsByAccount[allocation.id] else {
                throw LiveOrderError.invalidOrder
            }
            let key = allocation.id + ":" + contract.brokerContractId
            guard let held = positionsByAccountAndContract[key],
                  held >= allocation.contracts, allocation.contracts > 0 else {
                throw LiveOrderError.invalidOrder
            }
        }
    }
}

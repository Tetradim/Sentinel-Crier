import Foundation

/// The quantity selector always describes contracts, not shares.
enum MultiBrokerQuantityMode: String, Codable, CaseIterable, Identifiable {
    case perBroker
    case splitTotal
    var id: String { rawValue }
    var title: String {
        switch self {
        case .perBroker: return "Per broker"
        case .splitTotal: return "Split total"
        }
    }
}

struct MultiBrokerAllocation: Codable, Identifiable, Equatable {
    let brokerId: String
    let accountId: String
    let contracts: Int
    var id: String { brokerId + ":" + accountId }
}

enum MultiBrokerAllocationError: Error {
    case invalidQuantity
    case noAccounts
    case duplicateAccounts
    case insufficientContractsForEveryAccount
}

/// Deterministic allocation only. This does not place orders or estimate fills.
/// Split mode allocates one contract per account before distributing remainders.
/// The caller must separately verify per-account buying power and permissions.
enum MultiBrokerAllocator {
    static func allocate(
        quantity: Int,
        mode: MultiBrokerQuantityMode,
        accounts: [LiveAccount]
    ) throws -> [MultiBrokerAllocation] {
        guard quantity > 0 else { throw MultiBrokerAllocationError.invalidQuantity }
        guard !accounts.isEmpty else { throw MultiBrokerAllocationError.noAccounts }
        let ids = accounts.map(\.id)
        guard Set(ids).count == ids.count else { throw MultiBrokerAllocationError.duplicateAccounts }

        switch mode {
        case .perBroker:
            return accounts.map {
                MultiBrokerAllocation(brokerId: $0.brokerId,
                                      accountId: $0.accountId,
                                      contracts: quantity)
            }
        case .splitTotal:
            guard quantity >= accounts.count else {
                throw MultiBrokerAllocationError.insufficientContractsForEveryAccount
            }
            let each = quantity / accounts.count
            let remainder = quantity % accounts.count
            return accounts.enumerated().map { index, account in
                MultiBrokerAllocation(brokerId: account.brokerId,
                                      accountId: account.accountId,
                                      contracts: each + (index < remainder ? 1 : 0))
            }
        }
    }

    static func totalContracts(_ allocations: [MultiBrokerAllocation]) -> Int {
        allocations.reduce(0) { $0 + $1.contracts }
    }
}

import Foundation

/// Dispatches separately previewed and explicitly confirmed orders to
/// authorized live gateways. Broker results are independent, never atomic.
actor MultiBrokerExecutionCoordinator {
    struct BrokerOutcome {
        let brokerId: String
        let accountId: String
        let clientOrderId: String
        let receipt: LiveOrderReceipt?
        let errorDescription: String?
    }

    private var submittedIds = Set<String>()

    /// Must be invoked only from the explicit final confirmation action.
    /// Callers must persist the plan and submission intent on a secure backend
    /// before invoking this coordinator; in-memory dedupe is not crash-safe.
    func submitConfirmed(
        plan: MultiBrokerOrderPlan,
        gateway: LiveBrokerGateway
    ) async throws -> [BrokerOutcome] {
        try plan.validate()
        for request in plan.requests {
            guard !submittedIds.contains(request.clientOrderId) else {
                throw LiveOrderError.invalidOrder
            }
        }
        for request in plan.requests { submittedIds.insert(request.clientOrderId) }
        return await withTaskGroup(of: BrokerOutcome.self, returning: [BrokerOutcome].self) { group in
            for request in plan.requests {
                group.addTask {
                    do {
                        let receipt = try await gateway.submit(request)
                        return BrokerOutcome(brokerId: request.brokerId,
                            accountId: request.accountId,
                            clientOrderId: request.clientOrderId,
                            receipt: receipt, errorDescription: nil)
                    } catch {
                        // The broker may have accepted a request before timeout.
                        // Never resubmit blindly; reconcile by clientOrderId.
                        return BrokerOutcome(brokerId: request.brokerId,
                            accountId: request.accountId,
                            clientOrderId: request.clientOrderId,
                            receipt: nil, errorDescription: String(describing: error))
                    }
                }
            }
            var results = [BrokerOutcome]()
            for await outcome in group { results.append(outcome) }
            return results.sorted { $0.clientOrderId < $1.clientOrderId }
        }
    }
}

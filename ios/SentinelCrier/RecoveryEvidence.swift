import Foundation

struct RecoveryOrderEvidence: Identifiable {
    var id: String { ticket.id }
    let ticket: AlpacaTicket
    let order: AlpacaOrder?

    static func validate(_ order: AlpacaOrder, ticket: AlpacaTicket, previous: AlpacaOrder? = nil) throws {
        guard let filled = Decimal(string: order.filled_qty), !filled.isNaN else {
            throw AlpacaError.invalid("Broker filled quantity is invalid; preserve the original journal.")
        }
        var quantity = filled
        var integral = Decimal()
        NSDecimalRound(&integral, &quantity, 0, .plain)
        guard order.client_order_id == ticket.id, !order.id.isEmpty,
              order.symbol == ticket.symbol, order.side == ticket.side,
              order.qty.flatMap({ Decimal(string: $0) }) == Decimal(ticket.quantity),
              order.limit_price.flatMap({ Decimal(string: $0) }) == ticket.limitPrice,
              filled >= 0, filled <= Decimal(ticket.quantity),
              integral == filled else {
            throw AlpacaError.invalid("Broker evidence differs from the saved order. Preserve the original journal.")
        }
        let statuses: Set<String> = ["new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced", "pending_cancel", "pending_replace", "accepted", "pending_new", "accepted_for_bidding", "stopped", "rejected", "suspended", "calculated"]
        let terminal: Set<String> = ["filled", "canceled", "expired", "replaced", "rejected"]
        guard statuses.contains(order.status), order.status != "filled" || filled == Decimal(ticket.quantity) else {
            throw AlpacaError.invalid("Invalid broker order status or completed quantity. Preserve the original journal.")
        }
        guard filled == 0 || order.filled_avg_price != nil else {
            throw AlpacaError.invalid("Filled order has no economic evidence. Preserve the original journal.")
        }
        if let average = order.filled_avg_price {
            guard let price = Decimal(string: average), !price.isNaN, price > 0 else {
                throw AlpacaError.invalid("Invalid broker fill price. Preserve the original journal.")
            }
        }
        if let previous {
            // Validate retained evidence too; never treat corrupt local quantities as zero.
            try validate(previous, ticket: ticket)
            guard previous.id == order.id,
                  let oldFilled = Decimal(string: previous.filled_qty), filled >= oldFilled,
                  filled != oldFilled || previous.filled_avg_price == nil || order.filled_avg_price.flatMap({ Decimal(string: $0) }) == previous.filled_avg_price.flatMap({ Decimal(string: $0) }),
                  !terminal.contains(previous.status) || order.status == previous.status || order.status == "filled" else {
                throw AlpacaError.invalid("Broker identity, cumulative fill or terminal status regressed. Preserve the original journal.")
            }
        }
    }
}

struct RecoveryBrokerSnapshot {
    let accountID: String
    let environment: AlpacaEnvironment
    let checkedAt: Date
    let orders: [RecoveryOrderEvidence]
    let positions: [AlpacaPosition]
}

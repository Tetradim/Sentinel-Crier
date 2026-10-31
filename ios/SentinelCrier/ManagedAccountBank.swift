import Foundation

/// Broker reads are authoritative. Only this boundary can reserve managed
/// execution; it never retries a POST whose dispatch flag is durable.
@MainActor final class ManagedAccountBank {
    let bank: AccountIDBank; let scope: BankScope; let route: String
    init(bank: AccountIDBank, scope: BankScope, route: String) { self.bank = bank; self.scope = scope; self.route = route }
    static func funds(_ account: AlpacaAccount) throws -> (cash: Decimal, equity: Decimal) {
        guard account.currency == "USD", account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked,
              let cash = account.cash, let nonMargin = account.non_marginable_buying_power, let options = account.options_buying_power else { throw AlpacaError.invalid("Verified USD cash and non-margin/options buying power required for account bank.") }
        return (min(try AccountIDBank.money(cash), try AccountIDBank.money(nonMargin), try AccountIDBank.money(options)), try AccountIDBank.money(account.equity))
    }
    static func positions(_ rows: [AlpacaPosition]) throws -> [String: Int] {
        var result: [String: Int] = [:]
        for row in rows {
            guard result[row.symbol] == nil, let quantity = try? AccountIDBank.whole(row.qty), quantity >= 0,
                  row.asset_class == "us_equity" || row.asset_class == "us_option" else { throw AlpacaError.invalid("Bank requires supported whole long account positions.") }
            result[row.symbol] = quantity
        }
        return result
    }
    /// Admission scans actual retained journals; callers cannot assert a flat flag.
    static func verifyJournal(_ file: URL, api: AlpacaREST, scope: BankScope, bank: AccountIDBank?, route: String, undispatched: String? = nil) async throws {
        guard FileManager.default.fileExists(atPath: file.path) else {
            if let bank, try bank.snapshot(scope).journals[route + "|" + file.path] != nil { throw AlpacaError.invalid("Original managed journal is missing; preserve bank for recovery.") }
            return
        }
        let state = try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: file))
        guard state.accountID.isEmpty || state.accountID == scope.account else { throw AlpacaError.invalid("Retained journal belongs to another account.") }
        var failures: [String] = []
        if let bank, try bank.enabled(scope) {
            let retained = try bank.snapshot(scope)
            for lot in retained.lots where lot.route == route {
                for order in retained.orders where order.bankID == lot.id {
                    guard state.trades[lot.trade]?.mutations.contains(where: { $0.clientID == order.cid && $0.eventID == order.event && $0.sell == order.sell && $0.quantity == order.quantity }) == true else { throw AlpacaError.invalid("Original managed order evidence is missing from its journal.") }
                }
            }
        }
        for trade in state.trades.values {
            guard let event = trade.desired else { continue }
            guard event.environment == scope.environment else { throw AlpacaError.invalid("Retained journal environment mismatch.") }
            var owned = 0
            for mutation in trade.mutations {
                do {
                    try mutation.validateLocalDisposition()
                    if mutation.notSubmitted == true {
                        if let bank, let registered = try bank.order(scope, cid: mutation.clientID) {
                            guard registered.brokerID?.hasPrefix("local-no-post:") == true, registered.filled == 0, AccountIDBank.terminal.contains(registered.status) else { throw AlpacaError.invalid("Local refusal conflicts with retained bank evidence.") }
                        }
                        continue
                    }
                    if mutation.clientID.hasPrefix("sc-") {
                        if mutation.clientID == undispatched, mutation.order == nil {
                            if try bank?.order(scope, cid: mutation.clientID) == nil { continue }
                        }
                        guard let bank, let row = try bank.order(scope, cid: mutation.clientID),
                              let lot = try bank.snapshot(scope).lots.first(where: { $0.id == row.bankID }), lot.route == route, lot.trade == event.trade_id, lot.symbol == event.symbol, lot.asset == event.asset, row.event == mutation.eventID, row.sell == mutation.sell, row.quantity == mutation.quantity else { throw AlpacaError.invalid("Managed order missing from original account bank.") }
                        continue
                    }
                    let proof = try await api.order(clientID: mutation.clientID)
                    try mutation.validate(proof, symbol: event.symbol)
                    guard AccountIDBank.terminal.contains(proof.status), let filled = try? AccountIDBank.whole(proof.filled_qty) else { throw AlpacaError.invalid("Legacy order needs original-route recovery.") }
                    owned += mutation.sell ? -filled : filled
                } catch { failures.append(mutation.clientID + ": " + error.localizedDescription) }
            }
            if owned != 0 { failures.append(event.trade_id + ": close legacy holdings before setup") }
            if bank == nil && trade.mutations.isEmpty && trade.completed != event.event_id && !trade.invalidated { failures.append(event.trade_id + ": settle pending legacy instruction before setup") }
        }
        guard failures.isEmpty else { throw AlpacaError.invalid(failures.joined(separator: "\n")) }
    }
    static func verifyManual(_ file: URL, api: AlpacaREST, scope: BankScope) async throws {
        guard FileManager.default.fileExists(atPath: file.path) else { return }
        let state = try JSONDecoder().decode(AlpacaJournal.State.self, from: Data(contentsOf: file))
        var held: [String: Int] = [:]; var failures: [String] = []
        for row in state.submissions where row.ticket.environment == scope.environment && row.ticket.accountID == scope.account {
            if row.state.hasPrefix("rejected HTTP ") && row.order == nil { continue }
            do {
                let proof = try await api.order(clientID: row.ticket.id)
                guard proof.symbol == row.ticket.symbol, proof.side == row.ticket.side,
                      proof.client_order_id == row.ticket.id, proof.qty.flatMap({ try? AccountIDBank.whole($0) }) == row.ticket.quantity,
                      proof.limit_price.flatMap({ Decimal(string: $0) }) == row.ticket.limitPrice,
                      AccountIDBank.terminal.contains(proof.status), let filled = try? AccountIDBank.whole(proof.filled_qty), filled >= 0, filled <= row.ticket.quantity,
                      row.order == nil || row.order?.id == proof.id,
                      filled >= ((try? AccountIDBank.whole(row.order?.filled_qty ?? "0")) ?? 0) else { throw AlpacaError.invalid("Manual journal needs broker reconciliation.") }
                held[proof.symbol, default: 0] += proof.side == "sell" ? -filled : filled
            } catch { failures.append(row.ticket.id + ": " + error.localizedDescription) }
        }
        guard failures.isEmpty, held.values.allSatisfy({ $0 == 0 }) else { throw AlpacaError.invalid("Close and reconcile original manual orders before bank setup. " + failures.joined(separator: "; ")) }
    }
    func reconcile(api: AlpacaREST, undispatched: String? = nil) async throws {
        let account = try bank.snapshot(scope)
        var failures: [String] = []
        for (key, pairing) in account.journals {
            let parts = key.split(separator: "|", maxSplits: 1).map(String.init)
            do {
                guard parts.count == 2, FileManager.default.fileExists(atPath: parts[1]) else { throw AlpacaError.invalid("Retained bank journal unavailable.") }
                let file = URL(fileURLWithPath: parts[1])
                let state = try JSONDecoder().decode(IntentState.self, from: Data(contentsOf: file))
                guard state.pairingID.isEmpty || state.pairingID == pairing else { throw AlpacaError.invalid("Original pairing evidence changed.") }
                try await Self.verifyJournal(file, api: api, scope: scope, bank: bank, route: parts[0], undispatched: undispatched)
            } catch { failures.append(error.localizedDescription) }
        }
        // Include archived IDs: authoritative late fills must reactivate ownership.
        for order in account.orders {
            if order.brokerID?.hasPrefix("local-no-post:") == true { continue }
            do { try bank.observe(scope, await api.order(clientID: order.cid)) }
            catch { failures.append(order.cid + ": " + error.localizedDescription) }
        }
        do { try bank.inventory(scope, positions: Self.positions(await api.positions())) }
        catch { failures.append(error.localizedDescription) }
        guard failures.isEmpty else { throw AlpacaError.invalid("Account recovery required:\n" + failures.joined(separator: "\n")) }
    }
    func check(api: AlpacaREST, repair: Bool, canRepair: () -> Bool = { true }) async throws {
        let lease = try bank.lease(scope)
        defer { withExtendedLifetime(lease) {} }
        let initial = try await api.account()
        guard initial.id == scope.account, api.environment == scope.environment else { throw AlpacaError.invalid("Original broker account and environment required.") }
        try await reconcile(api: api)
        if repair {
            // Reconciliation queried every original broker ID, including retired
            // orders. Do not turn a failed/404/corrected proof into a reset.
            let positions = try Self.positions(await api.positions())
            try bank.inventory(scope, positions: positions)
            let current = try await api.account(); let observed = Date()
            guard canRepair(), current.id == scope.account, api.environment == scope.environment else { throw AlpacaError.invalid("Account identity changed during repair.") }
            let funds = try Self.funds(current)
            try bank.repairVerifiedFlat(scope, cash: funds.cash, equity: funds.equity, positions: positions, observedAt: observed)
        }
    }
    func prepare(api: AlpacaREST, event: IntentEvent, cid: String, quantity: Int, price: String?, sell: Bool, ordinal: Int, canSubmit: () -> Bool) async throws -> Date {
        do {
            try await reconcile(api: api, undispatched: cid)
            let binding = try await api.policyBinding(symbol: event.symbol, option: event.asset == "option", accountID: scope.account)
            guard binding.environment == scope.environment, binding.multiplier == (event.asset == "option" ? 100 : 1), let price else { throw IntentDispatchRefused() }
            let account = try await api.account(); let observed = Date()
            guard account.id == scope.account, api.environment == scope.environment, canSubmit() else { throw IntentDispatchRefused() }
            let funds = try Self.funds(account)
            try bank.rebaseIfFlat(scope, cash: funds.cash, equity: funds.equity)
            try bank.reserve(scope, route: route, trade: event.trade_id, event: event.event_id, cid: cid, symbol: event.symbol, asset: event.asset, multiplier: binding.multiplier, sell: sell, quantity: quantity, price: price, ordinal: ordinal, cash: funds.cash, equity: funds.equity)
            return observed
        } catch {
            // A pre-admission refusal is definite. A registered reservation remains
            // unknown unless the caller proves no POST could have started.
            if try bank.order(scope, cid: cid) == nil { throw IntentDispatchRefused() }
            throw error
        }
    }
}

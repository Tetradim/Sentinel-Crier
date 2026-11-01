import Foundation

@MainActor struct IntentExecutionAccess {
    let snapshot: () -> IntentState
    let commit: ((inout IntentState) throws -> Void) throws -> Void
    let api: () -> AlpacaREST?
    let pair: () -> IntentPairing?
    let bankRoute: String
    let managedBank: (AlpacaREST) throws -> ManagedAccountBank?
    let admission: () -> Bool
    let entryAllowed: (String) -> Bool
    let clock: () -> EntryClock.Reading?
    let now: () -> Date
    let monotonic: () -> TimeInterval
    let timerSession: () -> String
    let diagnostic: (String, String, String, Date) -> Void
    let brokerObserved: (String, String) -> Void
    let message: (String) -> Void
    let host: (String, String, Int, String, String?, String) throws -> String
    let enqueue: (@escaping @MainActor () async -> Void) -> Void
}

/// Reconciliation, cancellation and dispatch share one journal/session boundary.
/// This module cannot replace controller identity or write an unvalidated file.
@MainActor struct IntentExecution {
    let access: IntentExecutionAccess
    private var state: IntentState { access.snapshot() }
    private var api: AlpacaREST? { access.api() }
    private var pair: IntentPairing? { access.pair() }
    private var hosting: Bool { pair?.role == "host" }
    private var bankRoute: String { access.bankRoute }
    private var timerSession: String { access.timerSession() }
    private func commit(_ change: (inout IntentState) throws -> Void) throws { try access.commit(change) }
    private func managedBank(_ api: AlpacaREST) throws -> ManagedAccountBank? { try access.managedBank(api) }
    private func executionAdmission() -> Bool { access.admission() }
    private func now() -> Date { access.now() }
    private func monotonic() -> TimeInterval { access.monotonic() }
    private func diagnosticStep(_ id: String, _ stage: String, _ detail: String, at: Date = Date()) { access.diagnostic(id, stage, detail, at) }
    private func enqueueWork(_ work: @escaping @MainActor () async -> Void) { access.enqueue(work) }
    private func host(symbol: String, asset: String, quantity: Int, price: String, tradeID: String?, action: String) throws -> String { try access.host(symbol, asset, quantity, price, tradeID, action) }
    func reconcileBeforeResume(observe: NativeHealthObserver? = nil) async throws {
        guard let api else { return }
        let observed = observe
        let account = try await api.account()
        guard account.id == state.accountID, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Reconnect account is changed or blocked.") }
        observed?(.broker, .healthy, .verified)
        let managed = try managedBank(api)
        let accountLease = try managed.map { try $0.bank.lease($0.scope) }
        defer { withExtendedLifetime(accountLease) {} }
        var bankFailures: [String] = []
        if let managed { do { try await managed.reconcile(api: api) } catch { bankFailures.append(error.localizedDescription) } }
        var failures: [String] = bankFailures; var freshByTrade: [String: Set<Int>] = [:]; var failedTrades = Set<String>()
        for id in state.trades.keys.sorted() {
            guard let trade = state.trades[id], let event = trade.desired else { continue }
            if settled(trade) { continue }
            for index in trade.mutations.indices {
                let mutation = trade.mutations[index]
                do {
                    try mutation.validateLocalDisposition()
                    if mutation.notSubmitted == true { continue }
                    let order = try await api.order(clientID: mutation.clientID)
                    try mutation.validate(order, symbol: event.symbol)
                    try Task.checkCancellation()
                    guard self.api === api, pair != nil else { throw AlpacaError.invalid("Reconnect interrupted.") }
                    try recordReconciliation(id: id, index: index, order: order)
                    freshByTrade[id, default: []].insert(index)
                } catch {
                    try Task.checkCancellation()
                    guard self.api === api, pair != nil else { throw error }
                    failedTrades.insert(id)
                    failures.append(mutation.clientID + ": " + error.localizedDescription)
                }
            }
        }
        // Resume is cancellation-only: a failure elsewhere cannot prevent canceling a
        // separately freshly verified working order before the workspace disconnects.
        for id in freshByTrade.keys.sorted() {
            do {
                let cancelPending = try await cancelFreshWorkingMutation(id, api: api, freshIndexes: freshByTrade[id]!)
                if !cancelPending, !failedTrades.contains(id), let trade = state.trades[id], let event = trade.desired {
                    let stoppedEntry = event.action == "cancel" || ((trade.invalidated || trade.entryClosed == true) && event.action != "exit")
                    let stoppedExit = event.action == "exit" && trade.mutations.contains { $0.eventID == event.event_id && $0.order?.status != "filled" }
                    if stoppedEntry || stoppedExit { try completeTerminalInstruction(id, eventID: event.event_id) }
                }
            }
            catch {
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { throw error }
                failedTrades.insert(id)
                failures.append(id + ": " + error.localizedDescription)
            }
        }
        if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
    }

    private func recordReconciliation(id: String, index: Int, order: AlpacaOrder) throws {
        if let api, let managed = try managedBank(api), try managed.bank.order(managed.scope, cid: order.client_order_id) != nil { try managed.bank.observe(managed.scope, order) }
        access.brokerObserved(id, IntentDiagnosticRecord.timestamp())
        let uptime = monotonic(); let session = timerSession
        try commit { state in
            let prior = state.trades[id]!.mutations[index]
            state.trades[id]!.mutations[index].order = order
            guard !state.trades[id]!.mutations[index].sell, !terminal(order),
                  let seconds = state.trades[id]!.policySnapshot?.policy?.entry_timeout_seconds else { return }
            let mutation = state.trades[id]!.mutations[index]
            if let acknowledged = mutation.acknowledgedSession {
                if acknowledged != session || mutation.acknowledgedUptime.map({ uptime < $0 || uptime - $0 >= Double(seconds) }) != false {
                    state.trades[id]!.entryClosed = true
                }
            } else if prior.order != nil && prior.brokerResponseSession != session {
                // A previously known live order with absent acknowledgement evidence cannot get a renewed timer.
                state.trades[id]!.entryClosed = true
            } else {
                // Unknown POSTs first observed after restart start here, never at local reservation/POST.
                state.trades[id]!.mutations[index].acknowledgedSession = session
                state.trades[id]!.mutations[index].acknowledgedUptime = uptime
            }
        }
    }
    private func requiresCancellation(_ trade: IntentTrade, mutation: IntentMutation) -> Bool {
        guard let event = trade.desired,
              event.action != "enter" || trade.invalidated || trade.entryClosed == true else { return false }
        return mutation.eventID != event.event_id || event.action == "cancel" || ((event.action == "exit" || trade.entryClosed == true) && !mutation.sell)
    }
    private func cancelFreshWorkingMutation(_ id: String, api: AlpacaREST, freshIndexes: Set<Int>) async throws -> Bool {
        guard let trade = state.trades[id], let event = trade.desired else { return false }
        for index in trade.mutations.indices where freshIndexes.contains(index) {
            let mutation = trade.mutations[index]
            guard let order = mutation.order, !terminal(order), requiresCancellation(trade, mutation: mutation) else { continue }
            try Task.checkCancellation()
            guard self.api === api, let pairing = pair else { throw AlpacaError.invalid("Cancellation interrupted.") }
            let attemptTime = now()
            if let managed = try managedBank(api), mutation.clientID.hasPrefix("sc-") {
                guard let registered = try managed.bank.order(managed.scope, cid: mutation.clientID),
                      let owner = try managed.bank.snapshot(managed.scope).lots.first(where: { $0.id == registered.bankID }),
                      owner.route == bankRoute, owner.trade == id, registered.brokerID == order.id else { throw AlpacaError.invalid("Cancellation is not owned by this host route.") }
            }
            if mutation.mayRetryCancellation(now: attemptTime) {
                try commit {
                    $0.trades[id]!.mutations[index].cancelUnknown = true
                    $0.trades[id]!.mutations[index].cancelAttemptedAt = attemptTime
                }
                diagnosticStep(event.event_id, "cancel_dispatch", "broker=\(order.id)")
                try await api.cancel(orderID: order.id, canCancel: { [self] in
                    guard !Task.isCancelled, self.api === api, pair?.fingerprint == pairing.fingerprint,
                          let current = state.trades[id], current.mutations.indices.contains(index) else { return false }
                    let bound = current.mutations[index]
                    return bound.clientID == mutation.clientID && bound.order?.id == order.id && bound.order.map({ !terminal($0) }) == true && requiresCancellation(current, mutation: bound)
                })
            }
            return true // Cancellation was attempted or is awaiting fresh terminal proof/cooldown.
        }
        return false
    }
    private func settled(_ trade: IntentTrade) -> Bool {
        trade.desired != nil && trade.completed == trade.desired?.event_id && trade.mutations.allSatisfy { $0.notSubmitted == true || ($0.order.map(terminal) ?? false) }
    }
    private func completeTerminalInstruction(_ id: String, eventID: String) throws {
        // Call only after this pass successfully reconciled all broker-backed rows.
        try commit { state in
            guard let trade = state.trades[id], trade.desired?.event_id == eventID,
                  trade.mutations.allSatisfy({ $0.notSubmitted == true || ($0.order.map(terminal) ?? false) }) else { return }
            state.trades[id]!.completed = eventID
        }
        if state.trades[id]?.completed == eventID, let api, let managed = try managedBank(api) {
            try managed.bank.settleIfFlat(managed.scope, route: bankRoute, trade: id)
        }
    }
    private func terminal(_ order: AlpacaOrder) -> Bool { ["filled", "canceled", "expired", "rejected", "replaced"].contains(order.status) }
    func execute(_ id: String, api: AlpacaREST, observe: NativeHealthObserver? = nil) async throws {
        guard executionAdmission() else { throw AlpacaError.invalid("Account bank transition is running; execution stopped.") }
        guard let initial = state.trades[id], let desired = initial.desired else { return }
        let managed = try managedBank(api)
        let accountLease = try managed.map { try $0.bank.lease($0.scope) }
        defer { withExtendedLifetime(accountLease) {} }
        var bankFailure: Error?
        if let managed {
            // Recovery includes terminal and retired IDs before the settled shortcut.
            do { try await managed.reconcile(api: api) } catch { bankFailure = error }
            if desired.action == "exit" || desired.action == "cancel" { try managed.bank.invalidate(managed.scope, route: bankRoute, trade: id, reason: desired.action) }
        }
        if settled(initial) { if let bankFailure { throw bankFailure }; return }
        let account = try await api.account()
        guard account.id == state.accountID, desired.environment == api.environment, account.status == "ACTIVE", !account.account_blocked, !account.trading_blocked else { throw AlpacaError.invalid("Account is changed or blocked.") }
        observe?(.broker, .healthy, .verified)
        // Refresh every broker-backed mutation, including terminal records. An unrelated
        // lookup failure blocks new orders but must not conceal a separately verified cancelable buy.
        var freshIndexes = Set<Int>(); var failures: [String] = []
        for index in initial.mutations.indices {
            let mutation = state.trades[id]!.mutations[index]
            do {
                try mutation.validateLocalDisposition()
                if mutation.notSubmitted == true { continue }
                let order = try await api.order(clientID: mutation.clientID)
                try mutation.validate(order, symbol: desired.symbol)
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { return }
                diagnosticStep(mutation.eventID, "reconciled", "client=\(mutation.clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
                try recordReconciliation(id: id, index: index, order: order)
                freshIndexes.insert(index)
                if order.status == "rejected", hosting, state.trades[id]?.desired?.action != "cancel" {
                    _ = try host(symbol: desired.symbol, asset: desired.asset, quantity: desired.quantity, price: desired.limit_price, tradeID: id, action: "cancel")
                }
            } catch {
                try Task.checkCancellation()
                guard self.api === api, pair != nil else { return }
                failures.append(mutation.clientID + ": " + error.localizedDescription)
            }
        }
        guard let trade = state.trades[id], let e = trade.desired else { return }
        if try await cancelFreshWorkingMutation(id, api: api, freshIndexes: freshIndexes) {
            if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
            return
        }
        if !failures.isEmpty { throw AlpacaError.invalid("Broker reconciliation required: " + failures.joined(separator: "; ")) }
        if let bankFailure { throw bankFailure }
        if e.action == "cancel" || ((trade.invalidated || trade.entryClosed == true) && e.action != "exit") {
            diagnosticStep(e.event_id, "entry_invalidated", "Entry remainder canceled or superseded; tracked fills retained")
            try completeTerminalInstruction(id, eventID: e.event_id)
            return
        }
        if trade.mutations.contains(where: { $0.notSubmitted != true && ($0.order.map { !terminal($0) } ?? true) }) { return }
        if trade.completed == e.event_id { return }
        let sell = e.action == "exit"
        let existing = trade.mutations.filter { $0.eventID == e.event_id }
        if !sell && !existing.isEmpty {
            try completeTerminalInstruction(id, eventID: e.event_id)
            return
        }
        if sell && existing.contains(where: { $0.order?.status != "filled" }) {
            try completeTerminalInstruction(id, eventID: e.event_id)
            access.message("Exit is terminal or needs broker reconciliation; no duplicate sell submitted.")
            return
        }
        if !sell {
            guard let sample = access.clock() else {
                diagnosticStep(e.event_id, "entry_deferred", "clock_changed: check device time and reconnect; cancellation/exit handling remains active")
                access.message("New entry deferred: device clock changed. Check time and reconnect.")
                return
            }
            let currentTime = sample.effective
            if let created = IntentEvent.date(e.created_at), created > sample.wall {
                diagnosticStep(e.event_id, "entry_deferred", "Waiting for event creation time")
                return
            }
            guard trade.entrySkipped != true, access.entryAllowed(e.event_id),
                  let created = IntentEvent.date(e.created_at), let expires = IntentEvent.date(e.expires_at), expires > currentTime,
                  currentTime.timeIntervalSince(created) <= Double(hosting ? 30 : state.preferences.maxAgeSeconds),
                  e.quantity <= (hosting ? 1000 : state.preferences.maxQuantity) else {
                diagnosticStep(e.event_id, "entry_skipped", "Paused, expired, or outside local quantity/age limits")
                try commit { $0.trades[id]!.completed = e.event_id }; return
            }
        }
        guard let snapshot = trade.policySnapshot else { throw AlpacaError.invalid("Missing policy snapshot; preserve journal.") }
        try snapshot.validate(event: e)
        let policy = hosting ? nil : snapshot.policy
        if policy != nil {
            guard pair?.role == snapshot.role, pair?.fingerprint == snapshot.pairing,
                  snapshot.accountID.isEmpty || snapshot.accountID == account.id else { throw AlpacaError.invalid("Pinned policy pairing/account changed.") }
        }
        if !sell && policy != nil { try trade.validateBuyPlans(tradeID: id, history: state.received) }
        let preference = hosting ? IntentPreferences() : state.preferences
        var price = try preference.price(e.limit_price, sell: sell)
        var checkedBinding: IntentPolicyBinding?
        if policy != nil {
            let fresh = try await api.policyBinding(symbol: e.symbol, option: e.asset == "option", accountID: account.id)
            guard self.api === api, pair?.fingerprint == snapshot.pairing else { return }
            if let pinned = trade.policyBinding, pinned != fresh { throw AlpacaError.invalid("Pinned broker instrument/account binding changed.") }
            if trade.policyBinding == nil {
                try commit { $0.trades[id]!.policyBinding = fresh }
            }
            checkedBinding = fresh
        }
        let soldForRevision = trade.sold(for: e.event_id)
        var quantity = sell ? min(max(0, e.quantity - soldForRevision), trade.owned) : max(0, e.quantity - trade.owned)
        if let policy, let binding = checkedBinding {
            if sell {
                if policy.exit_mode == "close_tracked" { quantity = trade.owned }
                if policy.exit_mode == "proportional" { quantity = min(trade.owned, try trade.proportionalDue(event: e, history: state.received)) }
            } else {
                let plan: IntentEntryPlan
                if let frozen = trade.entryPlans?[e.event_id] {
                    try frozen.validate()
                    guard frozen.event == e, frozen.snapshot == snapshot, frozen.binding == binding else { throw AlpacaError.invalid("Frozen plan identity changed.") }
                    plan = frozen
                } else {
                    let needsCost = policy.mode == "budget" || policy.max_entry_notional != nil
                    let spent = needsCost ? try trade.premiumSpent(multiplier: binding.multiplier) : 0
                    let target = try policy.target(source: e.quantity, price: price, multiplier: binding.multiplier, bought: trade.bought, spent: spent)
                    plan = IntentEntryPlan(event: e, snapshot: snapshot, target: target, price: price, binding: binding, baselineBought: trade.bought, baselineSpent: NSDecimalNumber(decimal: spent).stringValue, pricingBasis: IntentPricingBasis(preference))
                    try plan.validate()
                    try commit { if $0.trades[id]!.entryPlans == nil { $0.trades[id]!.entryPlans = [:] }; $0.trades[id]!.entryPlans![e.event_id] = plan }
                }
                price = plan.price
                quantity = max(0, plan.target - trade.bought)
                if policy.mode == "budget" || policy.max_entry_notional != nil {
                    let spent = try trade.premiumSpent(multiplier: binding.multiplier)
                    guard let price else { throw AlpacaError.invalid("Final valuation unavailable.") }
                    let premium = try IntentBrokerDecimal.multiply(Decimal(quantity), IntentExecutionPolicy.money(price))
                    let reserved = try IntentBrokerDecimal.multiply(premium, Decimal(binding.multiplier))
                    let total = try IntentBrokerDecimal.add(spent, reserved)
                    if let budget = policy.budget, total > (try IntentExecutionPolicy.money(budget)) { throw AlpacaError.invalid("Entry budget exhausted.") }
                    if let cap = policy.max_entry_notional, total > (try IntentExecutionPolicy.money(cap)) { throw AlpacaError.invalid("Entry notional cap exceeded.") }
                }
            }
        }
        let desiredQuantity = quantity
        if sell {
            let positions = try await api.positions()
            let available = positions.first(where: { $0.symbol == e.symbol }).flatMap { Decimal(string: $0.qty_available ?? "0") } ?? 0
            quantity = min(quantity, max(0, NSDecimalNumber(decimal: available).intValue))
        }
        if sell && desiredQuantity > 0 && quantity == 0 { access.message("Waiting for tracked holdings to become available."); return }
        guard quantity > 0 else { try commit { $0.trades[id]!.completed = e.event_id }; return }
        // There must be no await between this revision check, durable unknown, and dispatch.
        guard state.trades[id]?.desired?.event_id == e.event_id, sell || state.trades[id]?.invalidated == false else { return }
        try Task.checkCancellation()
        guard self.api === api, pair != nil else { return }
        let clientID = managed.map { AccountIDBank.clientID($0.scope, route: bankRoute, trade: id, event: e.event_id, sell: sell, ordinal: existing.count) } ?? ("si-" + e.event_id + (sell ? "-s\(existing.count)" : "-b"))
        let mutation = IntentMutation(clientID: clientID, eventID: e.event_id, sell: sell, quantity: quantity)
        try commit { $0.trades[id]!.mutations.append(mutation) }
        let dispatched = Date()
        enqueueWork { [self] in diagnosticStep(e.event_id, "order_dispatch", "client=\(clientID) quantity=\(quantity) limit=\(price ?? "market")", at: dispatched) }
        var refusal = checkedBinding == nil ? "operation_stopped" : "metadata_or_operation_stopped"
        do {
            var bankObserved: Date?
            if let managed {
                bankObserved = try await managed.prepare(api: api, event: e, cid: clientID, quantity: quantity, price: price, sell: sell, ordinal: existing.count, canSubmit: { [self] in
                    executionAdmission() && !Task.isCancelled && self.api === api && pair != nil && state.trades[id]?.desired?.event_id == e.event_id
                })
                try managed.bank.markDispatching(managed.scope, cid: clientID)
            }
            let order = try await api.submitIntent(symbol: e.symbol, quantity: quantity, price: price, sell: sell, option: e.asset == "option", clientID: clientID, policyBinding: checkedBinding, canSubmit: { [self] in
                guard executionAdmission() else { refusal = "bank_transition"; return false }
                if let bankObserved, !(0...10).contains(Date().timeIntervalSince(bankObserved)) { refusal = "stale_bank_funds"; return false }
                guard !Task.isCancelled, self.api === api, pair != nil else { refusal = "operation_stopped"; return false }
                guard state.trades[id]?.desired?.event_id == e.event_id else { refusal = "revision_changed"; return false }
                guard hosting || state.preferences.samePricing(as: preference) else { refusal = "pricing_changed"; return false }
                if policy != nil {
                    guard pair?.fingerprint == snapshot.pairing, pair?.role == snapshot.role,
                          state.trades[id]?.policySnapshot == snapshot, state.trades[id]?.policyBinding == checkedBinding else { refusal = "policy_binding_changed"; return false }
                }
                if sell { return true }
                guard let sample = access.clock() else { refusal = "clock_changed"; return false }
                guard state.trades[id]?.invalidated == false, state.trades[id]?.entrySkipped != true, state.trades[id]?.entryClosed != true else { refusal = "invalidated"; return false }
                guard access.entryAllowed(e.event_id) else { refusal = "entries_paused"; return false }
                guard let created = IntentEvent.date(e.created_at), let expiry = IntentEvent.date(e.expires_at), sample.wall >= created else { refusal = "future_created_at"; return false }
                guard sample.effective < expiry else { refusal = "expired"; return false }
                guard sample.effective.timeIntervalSince(created) <= Double(hosting ? 30 : state.preferences.maxAgeSeconds) else { refusal = "max_age"; return false }
                guard e.quantity <= (hosting ? 1000 : state.preferences.maxQuantity) else { refusal = "max_quantity"; return false }
                if let policy {
                    guard pair?.fingerprint == snapshot.pairing, pair?.role == snapshot.role,
                          e.quantity <= policy.max_source_quantity,
                          state.trades[id]?.policySnapshot == snapshot, state.trades[id]?.policyBinding == checkedBinding else { refusal = "policy_binding_changed"; return false }
                }
                return true
            })
            try mutation.validate(order, symbol: e.symbol)
            if let managed { try managed.bank.observe(managed.scope, order) }
            diagnosticStep(e.event_id, "broker_response", "client=\(clientID) broker=\(order.id) status=\(order.status) filled=\(order.filled_qty) average=\(order.filled_avg_price ?? "unavailable")")
            try commit { s in let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!; s.trades[id]!.mutations[index].order = order; s.trades[id]!.mutations[index].brokerResponseSession = timerSession }
            if order.status == "rejected", hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        } catch is IntentDispatchRefused {
            if let managed, try managed.bank.order(managed.scope, cid: clientID) != nil { try managed.bank.notSubmitted(managed.scope, cid: clientID) }
            try commit { s in
                let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!
                s.trades[id]!.mutations[index].notSubmitted = true
                s.trades[id]!.completed = e.event_id
            }
            diagnosticStep(e.event_id, "order_not_submitted", refusal)
            access.message("Not submitted before dispatch: \(refusal). Journal retained; use a new revision if needed.")
        } catch AlpacaError.http(let code) where [400, 401, 403, 429].contains(code) {
            if let managed { try managed.bank.notSubmitted(managed.scope, cid: clientID) }
            diagnosticStep(e.event_id, "broker_rejected", "HTTP \(code)")
            // A definitive HTTP refusal is a local no-order disposition, never fabricated broker proof.
            try commit { s in
                let index = s.trades[id]!.mutations.firstIndex { $0.clientID == clientID }!
                s.trades[id]!.mutations[index].notSubmitted = true
                s.trades[id]!.completed = e.event_id
            }
            if hosting { _ = try host(symbol: e.symbol, asset: e.asset, quantity: e.quantity, price: e.limit_price, tradeID: id, action: "cancel") }
        }
    }
}

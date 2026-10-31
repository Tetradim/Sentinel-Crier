import Foundation
import CryptoKit
import Darwin

struct BankScope: Codable, Equatable {
    let account: String
    let environment: AlpacaEnvironment
    var key: String { environment.rawValue + ":" + account }
}

/// Short transactions reload protected state under flock. A separate nonblocking
/// lease spans broker reconciliation and dispatch, including every suspension.
/// Timeout, process death, and cancellation never free an unknown reservation.
@MainActor final class AccountIDBank {
    struct Policy: Codable { var mode: String; var value: String; var fee: String }
    struct Lot: Codable, Identifiable {
        let id: Int; let route: String; let trade: String; let symbol: String; let asset: String; let multiplier: Int
        var active = true; var invalid = false; var reason = ""
    }
    struct Order: Codable {
        let cid: String; let bankID: Int; let event: String; let sell: Bool; let ordinal: Int
        let quantity: Int; let price: Decimal; let fee: Decimal
        var status = "unknown"; var brokerID: String?; var filled = 0
        var cost = Decimal(0); var charge = Decimal(0); var basis = Decimal(0)
        var feeBooked = false; var dispatchStarted = false
    }
    struct Account: Codable {
        var available: Decimal; var equity: Decimal; var blocked = ""
        var baseline: [String: Int]; var policies: [String: Policy] = [:]; var pnl: [String: Decimal] = [:]
        var lots: [Lot] = []; var orders: [Order] = []
        var journals: [String: String] = [:]
        var audit: [String]? = nil
    }
    private struct State: Codable { var version = 1; var nextID = 1; var accounts: [String: Account] = [:] }
    final class Lease {
        private let fd: Int32
        init(_ file: URL) throws {
            fd = open(file.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
            guard fd >= 0 else { throw AlpacaError.invalid("Account bank lock unavailable.") }
            guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw AlpacaError.invalid("Another account operation is running. Retry after it reconciles.") }
        }
        deinit { flock(fd, LOCK_UN); close(fd) }
    }
    let file: URL
    static let terminal: Set<String> = ["filled", "canceled", "expired", "rejected", "replaced", "skipped"]
    init(file: URL) throws {
        self.file = file
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        _ = try transaction { _ in () }
    }
    static func local() throws -> AccountIDBank {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return try AccountIDBank(file: support.appendingPathComponent("account-id-bank-v1.json"))
    }
    private func transaction<T>(_ change: (inout State) throws -> T) throws -> T {
        let lease = try Lease(file.appendingPathExtension("transaction.lock"))
        defer { withExtendedLifetime(lease) {} }
        var state = FileManager.default.fileExists(atPath: file.path) ? try JSONDecoder().decode(State.self, from: Data(contentsOf: file)) : State()
        guard state.version == 1, state.nextID > 0 else { throw AlpacaError.invalid("Unsupported ID bank; preserve all journals.") }
        let value = try change(&state)
        try JSONEncoder().encode(state).write(to: file, options: [.atomic, .completeFileProtection])
        return value
    }
    func lease(_ scope: BankScope) throws -> Lease {
        try Lease(file.appendingPathExtension(Self.digest(scope.key) + ".dispatch.lock"))
    }
    private static func digest(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
    static func clientID(_ scope: BankScope, route: String, trade: String, event: String, sell: Bool, ordinal: Int) -> String {
        let parts = ["alpaca", scope.account, scope.environment.rawValue, route, trade, event, sell ? "sell" : "buy", String(ordinal)]
        let encoded = try! JSONEncoder().encode(parts)
        return "sc-" + digest(String(decoding: encoded, as: UTF8.self)).prefix(40)
    }
    static func money(_ value: String) throws -> Decimal {
        guard value.count <= 24,
              value.range(of: #"\A(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\z"#, options: .regularExpression) != nil,
              let number = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")), !number.isNaN, number >= 0 else { throw AlpacaError.invalid("Invalid account-bank amount.") }
        return number
    }
    static func whole(_ text: String) throws -> Int {
        let number = try money(text)
        guard number <= 1_000_000_000 else { throw AlpacaError.invalid("Invalid whole-unit quantity.") }
        let value = NSDecimalNumber(decimal: number).intValue
        guard Decimal(value) == number else { throw AlpacaError.invalid("Fractional inventory is unsupported.") }
        return value
    }
    private static func checked(_ a: Decimal, _ b: Decimal, multiply: Bool = false) throws -> Decimal {
        var a = a; var b = b; var result = Decimal()
        let status = multiply ? NSDecimalMultiply(&result, &a, &b, .plain) : NSDecimalAdd(&result, &a, &b, .plain)
        guard status == .noError, !result.isNaN else { throw AlpacaError.invalid("Account-bank arithmetic overflow.") }
        return result
    }
    static func product(_ values: Decimal...) throws -> Decimal { try values.reduce(Decimal(1)) { try checked($0, $1, multiply: true) } }
    private static func key(_ route: String, _ asset: String) -> String { route + ":" + asset }
    func enabled(_ scope: BankScope) throws -> Bool { try transaction { $0.accounts[scope.key] != nil } }
    func snapshot(_ scope: BankScope) throws -> Account {
        try transaction { state in
            guard let account = state.accounts[scope.key] else { throw AlpacaError.invalid("Account ID bank is not enabled.") }
            return account
        }
    }
    func enable(_ scope: BankScope, cash: Decimal, equity: Decimal, positions: [String: Int]) throws {
        guard !scope.account.isEmpty, cash >= 0, equity > 0, !cash.isNaN, !equity.isNaN, positions.values.allSatisfy({ $0 >= 0 }) else { throw AlpacaError.invalid("Verified USD funds and whole long inventory required.") }
        try transaction { state in
            if state.accounts[scope.key] == nil { state.accounts[scope.key] = Account(available: min(cash, equity), equity: equity, baseline: positions) }
        }
    }
    func configure(_ scope: BankScope, route: String, asset: String, mode: String, value: String, fee: String) throws {
        let amount = try Self.money(value); _ = try Self.money(fee)
        guard !route.isEmpty, ["stock", "option"].contains(asset), ["units", "dollars", "equity_percent"].contains(mode), mode != "equity_percent" || amount <= 100,
              mode != "units" || amount == Decimal(NSDecimalNumber(decimal: amount).intValue) else { throw AlpacaError.invalid("Invalid host pool.") }
        try update(scope) { $0.policies[Self.key(route, asset)] = Policy(mode: mode, value: value, fee: fee) }
    }
    private func update<T>(_ scope: BankScope, _ change: (inout Account) throws -> T) throws -> T {
        try transaction { state in
            guard var account = state.accounts[scope.key] else { throw AlpacaError.invalid("Account ID bank is not enabled.") }
            let result = try change(&account); state.accounts[scope.key] = account; return result
        }
    }
    func register(_ scope: BankScope, route: String, journal: URL, pairing: String) throws {
        guard journal.standardizedFileURL.path.hasPrefix(file.deletingLastPathComponent().standardizedFileURL.path + "/"), !pairing.isEmpty else { throw AlpacaError.invalid("Bank journal must stay in this private profile.") }
        try update(scope) { account in
            let key = route + "|" + journal.path
            guard account.journals[key] == nil || account.journals[key] == pairing else { throw AlpacaError.invalid("Account bank pairing changed.") }
            account.journals[key] = pairing
        }
    }
    func order(_ scope: BankScope, cid: String) throws -> Order? { try snapshot(scope).orders.first { $0.cid == cid } }
    private static func lot(_ account: Account, _ id: Int) throws -> (units: Int, basis: Decimal, pendingBuy: Int, pendingSell: Int, exposure: Decimal) {
        let rows = account.orders.filter { $0.bankID == id }
        let units = rows.reduce(0) { $0 + ($1.sell ? -$1.filled : $1.filled) }
        let basis = rows.reduce(Decimal(0)) { $0 + ($1.sell ? -$1.basis : $1.cost) }
        let buys = rows.filter { !$0.sell && !terminal.contains($0.status) }.reduce(0) { $0 + $1.quantity - $1.filled }
        let sells = rows.filter { $0.sell && !terminal.contains($0.status) }.reduce(0) { $0 + $1.quantity - $1.filled }
        let exposure = rows.reduce(Decimal(0)) { $0 + ($1.sell ? -$1.basis : $1.charge - ($1.feeBooked ? $1.fee : 0)) }
        guard units >= 0, basis >= 0, sells <= units else { throw AlpacaError.invalid("Contradictory host ownership.") }
        return (units, basis, buys, sells, max(0, exposure))
    }
    func reserve(_ scope: BankScope, route: String, trade: String, event: String, cid: String, symbol: String, asset: String, multiplier: Int, sell: Bool, quantity: Int, price: String, ordinal: Int, cash: Decimal, equity: Decimal) throws {
        let price = try Self.money(price)
        guard quantity > 0, quantity <= 1000, ordinal >= 0, price > 0, cash >= 0, equity > 0,
              ["stock", "option"].contains(asset), multiplier == (asset == "option" ? 100 : 1),
              [route, trade, event, symbol].allSatisfy({ !$0.isEmpty && $0.count <= 128 }),
              cid == Self.clientID(scope, route: route, trade: trade, event: event, sell: sell, ordinal: ordinal) else { throw AlpacaError.invalid("Invalid managed order identity, quantity or multiplier.") }
        try transaction { state in
            guard var account = state.accounts[scope.key] else { throw AlpacaError.invalid("Account bank not enabled.") }
            guard !account.orders.contains(where: { $0.cid == cid || ($0.event == event && $0.sell == sell && $0.ordinal == ordinal) }) else { throw AlpacaError.invalid("Source order already reserved. Reconcile; never resubmit.") }
            let index = account.lots.firstIndex { $0.route == route && $0.trade == trade }
            if let index {
                let old = account.lots[index]
                guard old.active, sell || !old.invalid, old.symbol == symbol, old.asset == asset, old.multiplier == multiplier else { throw AlpacaError.invalid("Retired or changed host ID.") }
            }
            let policyKey = Self.key(route, asset)
            let policy = account.policies[policyKey] ?? Policy(mode: "dollars", value: "0", fee: "0")
            let fee = try Self.money(policy.fee)
            var charge = Decimal(0)
            if sell {
                guard let index else { throw AlpacaError.invalid("No holdings owned by this host ID.") }
                let owned = try Self.lot(account, account.lots[index].id)
                guard quantity <= owned.units - owned.pendingSell, fee <= (try Self.product(price, Decimal(multiplier))) else { throw AlpacaError.invalid("Exit exceeds owned units or cannot cover fees.") }
            } else {
                guard account.blocked.isEmpty else { throw AlpacaError.invalid("Account requires reconciliation: " + account.blocked) }
                var units = 0; var exposure = Decimal(0)
                for lot in account.lots where lot.active && lot.route == route && lot.asset == asset {
                    let held = try Self.lot(account, lot.id); units += held.units + held.pendingBuy; exposure += held.exposure
                }
                var capacity = try Self.money(policy.value)
                if policy.mode == "equity_percent" { capacity = try Self.product(equity, capacity) / 100; var rounded = Decimal(); NSDecimalRound(&rounded, &capacity, 2, .down); capacity = rounded }
                charge = try Self.checked(Self.product(Decimal(quantity), price, Decimal(multiplier)), fee)
                if policy.mode == "units" { guard Decimal(units + quantity) <= capacity else { throw AlpacaError.invalid("Host unit pool exhausted.") } }
                else { capacity = max(0, capacity + min(0, account.pnl[policyKey] ?? 0)); guard exposure + charge <= capacity else { throw AlpacaError.invalid("Host monetary pool exhausted.") } }
                guard charge <= min(cash, equity, account.available) else { throw AlpacaError.invalid("Account cash is reserved or unavailable.") }
            }
            let identity: Int
            if let index { identity = account.lots[index].id }
            else { identity = state.nextID; state.nextID += 1; account.lots.append(Lot(id: identity, route: route, trade: trade, symbol: symbol, asset: asset, multiplier: multiplier)) }
            var order = Order(cid: cid, bankID: identity, event: event, sell: sell, ordinal: ordinal, quantity: quantity, price: price, fee: fee)
            order.charge = charge; account.available -= charge; account.equity = equity; account.orders.append(order)
            account.audit = (account.audit ?? []) + [Date().description + " reserved " + cid]
            state.accounts[scope.key] = account
        }
    }
    func markDispatching(_ scope: BankScope, cid: String) throws {
        try update(scope) { account in
            guard let index = account.orders.firstIndex(where: { $0.cid == cid }), !account.orders[index].dispatchStarted,
                  account.orders[index].status == "unknown" else { throw AlpacaError.invalid("Order already dispatched; reconcile without resending.") }
            account.orders[index].dispatchStarted = true
        }
    }
    func observe(_ scope: BankScope, _ proof: AlpacaOrder) throws {
        do { try update(scope) { account in
            guard let index = account.orders.firstIndex(where: { $0.cid == proof.client_order_id }), let li = account.lots.firstIndex(where: { $0.id == account.orders[index].bankID }) else { throw AlpacaError.invalid("Unknown account-bank proof.") }
            var order = account.orders[index]; let ownedLot = account.lots[li]
            let mutation = IntentMutation(clientID: order.cid, eventID: order.event, sell: order.sell, quantity: order.quantity)
            try mutation.validate(proof, symbol: ownedLot.symbol)
            guard proof.limit_price.flatMap({ Decimal(string: $0) }) == order.price, order.brokerID == nil || order.brokerID == proof.id,
                  let filled = try? Self.whole(proof.filled_qty), filled >= order.filled, proof.status != "filled" || filled == order.quantity,
                  !Self.terminal.contains(order.status) || Self.terminal.contains(proof.status) else { throw AlpacaError.invalid("Contradictory broker proof.") }
            let average = filled > 0 ? try Self.money(proof.filled_avg_price ?? "") : 0
            guard filled == 0 || average > 0 else { throw AlpacaError.invalid("Missing fill price.") }
            let cost = try Self.product(Decimal(filled), average, Decimal(ownedLot.multiplier))
            let delta = filled - order.filled; let deltaCost = cost - order.cost
            guard deltaCost >= 0, delta != 0 || deltaCost == 0,
                  order.sell ? deltaCost >= (try Self.product(Decimal(delta), order.price, Decimal(ownedLot.multiplier))) : deltaCost <= (try Self.product(Decimal(delta), order.price, Decimal(ownedLot.multiplier))) else { throw AlpacaError.invalid("Corrected or out-of-limit fill evidence.") }
            if Self.terminal.contains(order.status) && delta > 0 { account.blocked = "late_terminal_fill"; account.lots[li].active = true; account.lots[li].invalid = true; account.lots[li].reason = "late_terminal_fill" }
            let policyKey = Self.key(ownedLot.route, ownedLot.asset)
            if order.sell {
                let held = try Self.lot(account, order.bankID)
                guard delta <= held.units else { throw AlpacaError.invalid("Sale exceeds owned units.") }
                var released = delta == held.units ? held.basis : (delta == 0 ? 0 : held.basis * Decimal(delta) / Decimal(held.units))
                if delta != held.units { var rounded = Decimal(); NSDecimalRound(&rounded, &released, 8, .down); released = rounded }
                let fee = filled > 0 && !order.feeBooked ? order.fee : 0
                account.available += min(released, max(0, deltaCost - fee)); order.basis += released
                account.pnl[policyKey, default: 0] += deltaCost - released
            } else {
                let rest = Self.terminal.contains(proof.status) ? 0 : order.quantity - filled
                let charge = cost + (try Self.product(Decimal(rest), order.price, Decimal(ownedLot.multiplier))) + (filled > 0 || rest > 0 ? order.fee : 0)
                account.available += order.charge - charge; order.charge = charge
            }
            if filled > 0 && !order.feeBooked { account.pnl[policyKey, default: 0] -= order.fee; order.feeBooked = true }
            order.filled = filled; order.cost = cost; order.status = proof.status; order.brokerID = proof.id
            account.orders[index] = order
            if account.available < 0 { account.blocked = "capacity_deficit" }
            let held = try Self.lot(account, order.bankID)
            if held.units == 0 && account.orders.filter({ $0.bankID == order.bankID }).allSatisfy({ Self.terminal.contains($0.status) }), account.lots[li].invalid || account.orders.contains(where: { $0.bankID == order.bankID && $0.sell && $0.filled > 0 }) {
                account.lots[li].active = false; account.lots[li].invalid = true
            }
        } } catch { try? update(scope) { $0.blocked = "broker_evidence_conflict" }; throw error }
    }
    func notSubmitted(_ scope: BankScope, cid: String) throws {
        let account = try snapshot(scope)
        guard let order = account.orders.first(where: { $0.cid == cid }), order.brokerID == nil, order.filled == 0,
              let lot = account.lots.first(where: { $0.id == order.bankID }) else { throw AlpacaError.invalid("Cannot erase broker evidence.") }
        try observe(scope, AlpacaOrder(id: "local-no-post:" + cid, client_order_id: cid, symbol: lot.symbol, status: "rejected", qty: String(order.quantity), limit_price: NSDecimalNumber(decimal: order.price).stringValue, filled_qty: "0", filled_avg_price: nil, side: order.sell ? "sell" : "buy"))
        try invalidate(scope, route: lot.route, trade: lot.trade, reason: "not_submitted")
    }
    func invalidate(_ scope: BankScope, route: String, trade: String, reason: String) throws {
        try update(scope) { account in
            guard let index = account.lots.firstIndex(where: { $0.route == route && $0.trade == trade }) else { return }
            account.lots[index].invalid = true; account.lots[index].reason = reason
            let held = try Self.lot(account, account.lots[index].id)
            if held.units == 0 && account.orders.filter({ $0.bankID == account.lots[index].id }).allSatisfy({ Self.terminal.contains($0.status) }) { account.lots[index].active = false }
        }
    }
    func settleIfFlat(_ scope: BankScope, route: String, trade: String) throws {
        try update(scope) { account in
            guard let index = account.lots.firstIndex(where: { $0.route == route && $0.trade == trade }) else { return }
            let identity = account.lots[index].id
            let held = try Self.lot(account, identity)
            guard held.units == 0, held.pendingBuy == 0, held.pendingSell == 0,
                  account.orders.filter({ $0.bankID == identity }).allSatisfy({ Self.terminal.contains($0.status) }) else { return }
            account.lots[index].active = false; account.lots[index].invalid = true
            if account.lots[index].reason.isEmpty { account.lots[index].reason = "settled_empty" }
            account.audit = (account.audit ?? []) + [Date().description + " retired_settled_empty id=" + String(identity)]
        }
    }
    func retire(_ scope: BankScope, route: String, trade: String, reason: String) throws {
        let account = try snapshot(scope)
        guard let lot = account.lots.first(where: { $0.route == route && $0.trade == trade }) else { throw AlpacaError.invalid("Unknown owned ID.") }
        let held = try Self.lot(account, lot.id)
        guard held.units == 0, account.orders.filter({ $0.bankID == lot.id }).allSatisfy({ Self.terminal.contains($0.status) }) else { throw AlpacaError.invalid("ID retains holdings or unresolved orders.") }
        try invalidate(scope, route: route, trade: trade, reason: reason)
    }
    func inventory(_ scope: BankScope, positions: [String: Int]) throws {
        let mismatch = try update(scope) { account -> Bool in
            guard positions.values.allSatisfy({ $0 >= 0 }) else { throw AlpacaError.invalid("Unsupported inventory.") }
            var expected = account.baseline
            for lot in account.lots { expected[lot.symbol, default: 0] += try Self.lot(account, lot.id).units }
            let mismatch = Set(expected.keys).union(positions.keys).contains { expected[$0, default: 0] != positions[$0, default: 0] }
            if mismatch && account.blocked.isEmpty { account.blocked = "position_discrepancy" }
            if !mismatch && account.blocked == "position_discrepancy" { account.blocked = "" }
            return mismatch
        }
        if mismatch { throw AlpacaError.invalid("Broker inventory differs from host ownership and external baseline. Entries blocked.") }
    }
    func repairVerifiedFlat(_ scope: BankScope, cash: Decimal, equity: Decimal, positions: [String: Int], observedAt: Date, now: Date = Date()) throws {
        guard (0...10).contains(now.timeIntervalSince(observedAt)), cash >= 0, equity > 0 else { throw AlpacaError.invalid("Fresh account funds required for explicit repair.") }
        try update(scope) { account in
            guard ["", "capacity_deficit", "late_terminal_fill", "broker_evidence_conflict", "position_discrepancy"].contains(account.blocked),
                  account.orders.allSatisfy({ Self.terminal.contains($0.status) }),
                  try account.lots.allSatisfy({ try Self.lot(account, $0.id).units == 0 }),
                  Set(account.baseline.keys).union(positions.keys).allSatisfy({ account.baseline[$0, default: 0] == positions[$0, default: 0] }) else { throw AlpacaError.invalid("Repair requires verified flat Crier holdings, terminal original orders and unchanged external baseline.") }
            let previous = account.blocked
            account.available = min(cash, equity); account.equity = equity; account.blocked = ""
            for index in account.lots.indices { account.lots[index].active = false; account.lots[index].invalid = true; if account.lots[index].reason.isEmpty { account.lots[index].reason = "verified_flat_repair" } }
            account.audit = (account.audit ?? []) + [Date().description + " explicit_verified_flat_repair previous=" + previous]
        }
    }
    func rebaseIfFlat(_ scope: BankScope, cash: Decimal, equity: Decimal) throws {
        try update(scope) { account in
            if account.blocked.isEmpty && !account.lots.contains(where: { $0.active }) && account.orders.allSatisfy({ Self.terminal.contains($0.status) }) { account.available = min(cash, equity); account.equity = equity }
        }
    }
}

import Foundation

/// Bank setup receives retained journal references and a current-session fence.
/// It cannot replace workspace identity, credentials, or execution permission.
@MainActor enum AccountBankRecovery {
    struct Journal {
        let intent: IntentController?
        let manualFile: URL?
        let route: String
    }
    static func setup(bank: AccountIDBank, scope: BankScope, route: String, intent: IntentController, pairing: IntentPairing,
                      journals: [Journal], client: AlpacaREST, stillCurrent: () -> Bool) async throws {
        let current = try await client.account()
        guard stillCurrent(), current.id == scope.account, client.environment == scope.environment else { throw AlpacaError.invalid("Authenticated account changed. Setup refused.") }
        for journal in journals {
            if let controller = journal.intent, controller.state.accountID == scope.account {
                try await ManagedAccountBank.verifyJournal(controller.journalFile, api: client, scope: scope, bank: (try bank.enabled(scope)) ? bank : nil, route: journal.route)
            }
            if let file = journal.manualFile { try await ManagedAccountBank.verifyManual(file, api: client, scope: scope) }
            guard stillCurrent() else { throw AlpacaError.invalid("Bank setup session changed.") }
        }
        let positions = try ManagedAccountBank.positions(await client.positions())
        let refreshed = try await client.account()
        guard stillCurrent(), refreshed.id == scope.account else { throw AlpacaError.invalid("Account or foreground session changed during setup.") }
        let funds = try ManagedAccountBank.funds(refreshed)
        try bank.enable(scope, cash: funds.cash, equity: funds.equity, positions: positions)
        try bank.inventory(scope, positions: positions)
        try intent.persistBankJournal()
        try bank.register(scope, route: route, journal: intent.journalFile, pairing: pairing.fingerprint)
        for journal in journals { try journal.intent?.installAccountBank(bank, route: journal.route) }
    }
}

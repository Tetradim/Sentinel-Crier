import SwiftUI

struct AlpacaTradingView: View {
    @EnvironmentObject var model: AlpacaWorkspace
    @State private var symbol = ""
    @State private var expiration = ""
    @State private var options = false
    @State private var contractID = ""
    @State private var quantity = 1
    @State private var limit = ""
    @State private var sell = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("ORDER TICKET").font(.caption.weight(.semibold)).tracking(1.5).foregroundStyle(.secondary)
                            Text(sell ? "Close position" : "Open position").font(.title2.weight(.bold))
                        }
                        Spacer()
                        Text(model.environment.rawValue.uppercased())
                            .font(.caption.weight(.bold)).padding(8)
                            .background(Color.blue.opacity(0.16), in: Capsule())
                    }
                    Text("Alpaca • Limit order • Day duration")
                        .font(.caption).foregroundStyle(.secondary)
                    if model.account == nil {
                        Label("Connect an account before reviewing an order", systemImage: "info.circle")
                            .font(.subheadline).foregroundStyle(.secondary)
                    }
                    if model.purpose == .alerts {
                        NavigationLink("Choose Trade or Follow in setup", destination: GuidedSetupView())
                    }
                }
                Section("Instrument") {
                    Picker("Asset type", selection: $options) {
                        Text("Stocks").tag(false)
                        Text("Options").tag(true)
                    }.pickerStyle(.segmented)
                    TextField("Underlying / stock symbol", text: $symbol).textInputAutocapitalization(.characters).autocorrectionDisabled()
                    if options {
                        TextField("Expiration YYYY-MM-DD", text: $expiration).keyboardType(.numbersAndPunctuation)
                        Button("Discover option contracts") { Task { await model.discover(symbol: symbol, expiration: expiration) } }
                        Picker("Contract", selection: $contractID) {
                            Text("Choose contract").tag("")
                            ForEach(model.contracts) { Text($0.name).tag($0.id) }
                        }
                        if let selected = model.contracts.first(where: { $0.id == contractID }) {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(selected.type.uppercased()).font(.caption.weight(.bold))
                                    Spacer()
                                    Text("Strike $" + selected.strike_price).monospacedDigit()
                                }
                                Text("Expires " + selected.expiration_date).font(.subheadline)
                                Text(selected.symbol).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            }.padding(.vertical, 6)
                                .accessibilityElement(children: .combine)
                        } else {
                            Text("Discover and choose an exact contract before reviewing. No bid/ask quote is supplied by this selector.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }.disabled(model.busy || model.review != nil)
                Section("Order details") {
                    Picker("Order side", selection: $sell) {
                        Text(options ? "Buy to open" : "Buy shares").tag(false)
                        Text(options ? "Sell to close" : "Sell shares").tag(true)
                    }.pickerStyle(.segmented)
                    Stepper("\(options ? "Contracts" : "Shares"): \(quantity)", value: $quantity, in: 1...1000)
                        .monospacedDigit()
                    TextField(options ? "Limit premium per share" : "Limit price per share", text: $limit).keyboardType(.decimalPad)
                    if options {
                        Text("Standard contracts represent 100 shares. Premium × 100 × contracts determines limit notional, before fees.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Button("Review order") {
                        Task { await model.prepare(symbol: symbol, quantity: quantity, limit: limit, sell: sell, contract: options ? model.contracts.first(where: { $0.id == contractID }) : nil) }
                    }.buttonStyle(.borderedProminent).controlSize(.large)
                        .accessibilityIdentifier("crier.order.review")
                        .disabled(model.account == nil || model.purpose == .alerts || (options && !model.contracts.contains(where: { $0.id == contractID })))
                }.disabled(model.busy || model.review != nil)
                if let ticket = model.review {
                    Section("Final confirmation • \(ticket.environment.rawValue.uppercased())") {
                        Text("\(ticket.side.uppercased()) \(ticket.quantity) \(ticket.symbol) @ $\(NSDecimalNumber(decimal: ticket.limitPrice).stringValue)")
                            .font(.headline).monospacedDigit().textSelection(.enabled)
                        Text("Limit notional: $\(NSDecimalNumber(decimal: ticket.limitPrice * Decimal(ticket.quantity * ticket.multiplier)).stringValue). Fees excluded; execution not guaranteed.")
                        Text("Account: \(ticket.accountID)").font(.caption).textSelection(.enabled)
                        Text("Client ID: \(ticket.id)").font(.caption).textSelection(.enabled)
                        Button(ticket.environment == .live ? "CONFIRM REAL-MONEY ORDER" : "Confirm paper order", role: ticket.environment == .live ? .destructive : nil) { Task { await model.confirm(ticket) } }.disabled(model.busy)
                        Button("Discard review") { model.review = nil }.disabled(model.busy)
                    }
                }
                Section { Text(model.message).font(.footnote) }
                if let intent = model.intent { IntentTradesView(controller: intent) }
                Section("Saved orders • pull to reconcile") {
                    ForEach(model.submissions.reversed()) { submission in
                        VStack(alignment: .leading) {
                            Text("\(submission.ticket.symbol) • \(submission.state)")
                            Text(submission.id).font(.caption).textSelection(.enabled)
                            if submission.order != nil {
                                Button("Request cancellation", role: .destructive) { Task { await model.cancel(submission) } }.disabled(model.busy)
                            }
                        }
                    }
                }
            }.scrollContentBackground(.hidden)
                .background(Color(red: 0.035, green: 0.045, blue: 0.06))
                .navigationTitle("Trade").navigationBarTitleDisplayMode(.inline)
                .refreshable { await model.refresh() }
        }
    }
}

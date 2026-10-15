import SwiftUI

/// A live-only order ticket. Until broker discovery, live contract resolution,
/// server-side preview, and authorization are active, submission stays absent.
struct LiveTradingHome: View {
    @State private var symbol = ""
    @State private var expiration = Date()
    @State private var limitText = ""
    @State private var selectedAction: LiveOrderAction = .buyToOpen
    @AppStorage(TradingPreferences.quantityModeKey) private var savedMode = MultiBrokerQuantityMode.perBroker.rawValue
    @AppStorage(TradingPreferences.contractQuantityKey) private var contractQuantity = 1

    private var mode: Binding<MultiBrokerQuantityMode> {
        Binding(
            get: { TradingPreferences.mode(rawValue: savedMode) },
            set: { savedMode = $0.rawValue }
        )
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Option") {
                    TextField("Underlying symbol", text: $symbol)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                    DatePicker("Expiration", selection: $expiration, displayedComponents: .date)
                    Label("Choose a live contract from the options chain", systemImage: "magnifyingglass")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Order") {
                    Picker("Action", selection: $selectedAction) {
                        Text("Buy to Open").tag(LiveOrderAction.buyToOpen)
                        Text("Sell to Close").tag(LiveOrderAction.sellToClose)
                        Text("Sell to Open").tag(LiveOrderAction.sellToOpen)
                        Text("Buy to Close").tag(LiveOrderAction.buyToClose)
                    }
                    Picker("Quantity", selection: mode) {
                        ForEach(MultiBrokerQuantityMode.allCases) { option in
                            Text(option.title).tag(option)
                        }
                    }
                    .pickerStyle(.segmented)
                    Stepper("Contracts: \(contractQuantity)", value: $contractQuantity, in: 1...1000)
                    HStack {
                        Text("Limit price")
                        Spacer()
                        TextField("Required", text: $limitText)
                            .keyboardType(.decimalPad)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 110)
                    }
                    Text(mode.wrappedValue == .perBroker
                        ? "The entered quantity applies to every selected account."
                        : "The entered quantity is split across the selected accounts.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Brokerage selection") {
                    Label("No authorized accounts available", systemImage: "building.columns")
                        .foregroundStyle(.secondary)
                    Text("Each selected account must receive a separate broker-resolved contract and current order preview.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Combined order review") {
                    Label("Not ready to submit", systemImage: "lock.shield")
                        .foregroundStyle(.orange)
                    Text("Submission is disabled until official brokerage authorization, durable server-side idempotency, broker previews and a final customer confirmation are available.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("No quotes or estimated fills are invented.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Trade")
        }
    }
}

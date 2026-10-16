import SwiftUI

/// Webull-inspired stock/contract chart controls, with no unlicensed demo data.
/// This view intentionally owns no order-entry or account authorization logic.
struct TradingChartWorkspace: View {
    var feed: (any LiveChartFeed)? = nil

    @State private var ticker = "SPY"
    @State private var contractId = ""
    @State private var showOption = false
    @State private var snapshot: ChartSnapshot?
    @State private var busy = false
    @State private var message: String?
    @State private var fullscreen = false
    @State private var showIndicators = false
    @AppStorage("chart.timeframe") private var savedTimeframe = ChartTimeframe.oneMinute.rawValue
    @AppStorage("chart.ema9") private var ema9 = true
    @AppStorage("chart.ema20") private var ema20 = true
    @AppStorage("chart.ema50") private var ema50 = false
    @AppStorage("chart.volume") private var showVolume = true

    private var timeframe: ChartTimeframe {
        ChartTimeframe(rawValue: savedTimeframe) ?? .oneMinute
    }

    private var enabledEMAs: [Int] {
        var result: [Int] = []
        if ema9 { result.append(9) }
        if ema20 { result.append(20) }
        if ema50 { result.append(50) }
        return result
    }

    private var instrument: ChartInstrument? {
        let symbol = ticker.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !symbol.isEmpty, symbol.count <= 12,
              symbol.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }) else {
            return nil
        }
        if showOption {
            let option = contractId.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
            guard !option.isEmpty, option.count <= 32,
                  option.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else {
                return nil
            }
            return .option(underlying: symbol, contractId: option)
        }
        return .stock(symbol: symbol)
    }

    private var requestKey: String {
        "\(ticker):\(contractId):\(showOption):\(savedTimeframe)"
    }

    var body: some View {
        VStack(spacing: 12) {
            search
            Picker("Chart instrument", selection: $showOption) {
                Text("Stock").tag(false)
                Text("Option").tag(true)
            }
            .pickerStyle(.segmented)

            if showOption {
                TextField("Exact option contract (OCC symbol)", text: $contractId)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                    .accessibilityHint("Select the exact contract from the live options chain when connected")
            }
            HStack(spacing: 6) {
                ForEach(ChartTimeframe.allCases) { frame in
                    Button(frame.rawValue) { savedTimeframe = frame.rawValue }
                        .font(.system(size: 12, weight: .semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 9)
                        .background(frame == timeframe ? Color.blue : Color.gray.opacity(0.15),
                                    in: RoundedRectangle(cornerRadius: 7))
                        .foregroundStyle(frame == timeframe ? .white : .primary)
                }
            }
            chartBody(height: 290)
            HStack {
                Button {
                    showIndicators = true
                } label: {
                    Label("Indicators", systemImage: "slider.horizontal.3")
                }
                .font(.subheadline)
                Spacer()
                Button {
                    fullscreen = true
                } label: {
                    Label("Expand", systemImage: "arrow.up.left.and.arrow.down.right")
                }
                .font(.subheadline)
            }
            .padding(.horizontal, 2)
        }
        .task(id: requestKey) { await load() }
        .sheet(isPresented: $showIndicators) { indicatorSheet }
        .fullScreenCover(isPresented: $fullscreen) {
            NavigationStack {
                VStack(spacing: 12) {
                    Text(instrument?.title ?? "Choose an instrument")
                        .font(.headline)
                    chartBody(height: 490)
                    Spacer(minLength: 0)
                }
                .padding()
                .navigationTitle("Chart")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { fullscreen = false }
                    }
                }
            }
            .preferredColorScheme(.dark)
        }
    }

    private var search: some View {
        HStack {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Stock ticker", text: $ticker)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
            if busy { ProgressView().controlSize(.small) }
        }
        .padding(11)
        .background(Color.gray.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
    }

    private func chartBody(height: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let snapshot, !snapshot.candles.isEmpty,
               snapshot.instrument == instrument && snapshot.timeframe == timeframe {
                HStack {
                    Text(snapshot.instrument.title).font(.headline)
                    Spacer()
                    Text(snapshot.isDelayed ? "Delayed data" : "Provider data")
                        .foregroundStyle(snapshot.isDelayed ? .orange : .secondary)
                        .font(.caption)
                }
                TradingCandleCanvas(candles: snapshot.candles,
                                    emaPeriods: enabledEMAs, showVolume: showVolume)
                    .frame(height: height)
                HStack {
                    ForEach(enabledEMAs, id: \.self) { period in
                        Text("EMA \(period)")
                            .font(.caption2)
                            .foregroundStyle(emaColor(period))
                    }
                    Spacer()
                    Text(snapshot.source).font(.caption2).foregroundStyle(.secondary)
                }
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "chart.xyaxis.line")
                        .font(.largeTitle)
                        .foregroundStyle(.secondary)
                    Text(showOption ? "Option contract chart unavailable" : "Stock chart unavailable")
                        .font(.headline)
                    Text(message ?? "Connect a licensed live market-data feed to view actual candles and EMAs.")
                        .font(.footnote)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                    if showOption {
                        Text("Option charts use the exact contract's trade history, never estimated prices from the stock.")
                            .font(.caption)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: height)
                .padding(.horizontal, 14)
                .background(Color.gray.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private func emaColor(_ period: Int) -> Color {
        switch period {
        case 9: return .yellow
        case 20: return .cyan
        default: return .purple
        }
    }

    private var indicatorSheet: some View {
        NavigationStack {
            Form {
                Section("Moving averages") {
                    Toggle("EMA 9", isOn: $ema9)
                    Toggle("EMA 20", isOn: $ema20)
                    Toggle("EMA 50", isOn: $ema50)
                    Text("EMA periods are configurable. The customer's final default preset is not yet selected.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Chart details") {
                    Toggle("Volume", isOn: $showVolume)
                    Text("EMAs use a historical warm-up and show no values until enough bars are present.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Indicators")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { showIndicators = false }
                }
            }
        }
    }

    @MainActor
    private func load() async {
        snapshot = nil
        message = nil
        guard let instrument else {
            message = showOption ? "Choose a valid option contract." : "Enter a valid ticker."
            return
        }
        guard let feed else {
            message = "Live chart provider not yet connected."
            return
        }
        busy = true
        defer { busy = false }
        do {
            let received = try await feed.load(instrument: instrument, timeframe: timeframe, limit: 400)
            try received.validate()
            guard received.instrument == instrument && received.timeframe == timeframe else {
                throw ChartDataError.invalidPayload
            }
            snapshot = received
            if received.candles.isEmpty { message = "No trading bars available for this instrument." }
        } catch {
            message = "The live market-data provider could not supply this chart."
        }
    }
}

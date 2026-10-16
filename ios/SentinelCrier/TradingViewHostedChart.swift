import SwiftUI
import WebKit

/// DISPLAY ONLY: TradingView-hosted chart widget.
///
/// TradingView widgets may display TradingView-sourced market data, unlike the
/// Lightweight Charts library (which has no market data). Widgets are not an
/// authorized data API: do not read JS/DOM prices, export chart values, populate
/// an order ticket, or use these prices for order decisions or fill verification.
///
/// Commercial embedded/mobile usage and permitted market coverage must be
/// approved under TradingView's applicable terms and data provider licenses.
/// Disabled until that is confirmed. This flag must not be toggled by a user
/// preference, because a toggle is not a commercial/data license.
enum TradingViewChartPolicy {
    static let commercialEmbedApproved = false
}

/// Only standard listed US ETF/equity symbols are supported by this adapter.
/// OCC option contracts require their own licensed feed and are NOT translated
/// into an underlying-stock price chart.
enum TradingViewDisplaySymbol {
    static func listedETF(_ ticker: String) -> String? {
        let symbol = ticker.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard symbol.range(of: #"^[A-Z]{1,5}$"#, options: .regularExpression) != nil else {
            return nil
        }
        return "AMEX:\(symbol)"
    }
}

struct TradingViewHostedChart: View {
    let ticker: String
    let timeframe: ChartTimeframe

    var body: some View {
        Group {
            if !TradingViewChartPolicy.commercialEmbedApproved {
                ContentUnavailableView(
                    "TradingView chart not enabled",
                    systemImage: "chart.xyaxis.line",
                    description: Text("Embedded TradingView data requires verified commercial display permissions. Crier will not use widget prices for trading orders.")
                )
            } else if let symbol = TradingViewDisplaySymbol.listedETF(ticker) {
                TradingViewWebWidget(symbol: symbol, timeframe: timeframe)
            } else {
                ContentUnavailableView(
                    "Symbol unavailable", systemImage: "exclamationmark.triangle",
                    description: Text("Choose a supported listed stock or ETF.")
                )
            }
        }
    }
}

private struct TradingViewWebWidget: UIViewRepresentable {
    let symbol: String
    let timeframe: ChartTimeframe

    private var widgetInterval: String {
        switch timeframe {
        case .oneMinute: return "1"
        case .fiveMinutes: return "5"
        case .fifteenMinutes: return "15"
        case .oneHour: return "60"
        case .oneDay: return "D"
        }
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        view.isOpaque = false
        view.backgroundColor = .black
        view.navigationDelegate = context.coordinator
        loadWidget(in: view)
        return view
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let key = "\(symbol):\(widgetInterval)"
        if context.coordinator.loadedKey != key {
            loadWidget(in: webView)
            context.coordinator.loadedKey = key
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    private func loadWidget(in view: WKWebView) {
        // All interpolated values have been reduced to allowlisted
        // symbol/timeframe strings. Never embed credentials or arbitrary HTML.
        let html = """
        <!doctype html><html lang="en"><head>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
        html,body{margin:0;background:#10131b;color:white;height:100%}
        .tradingview-widget-container{height:100%;width:100%}
        .tradingview-widget-container__widget{height:calc(100% - 32px);width:100%}
        .tradingview-widget-copyright{font:12px -apple-system,sans-serif;padding:6px}
        a{color:#81b8fc}
        </style></head><body>
        <div class="tradingview-widget-container">
          <div class="tradingview-widget-container__widget"></div>
          <div class="tradingview-widget-copyright">
            <a href="https://www.tradingview.com/" rel="noopener noreferrer">
              Charts by TradingView
            </a>
          </div>
          <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
          {"autosize":true,"symbol":"\(symbol)","interval":"\(widgetInterval)",
           "timezone":"America/New_York","theme":"dark","style":"1",
           "locale":"en","allow_symbol_change":false,"hide_side_toolbar":true,
           "hide_top_toolbar":false,"hide_legend":false,"hide_volume":false,
           "withdateranges":true,"studies":["Moving Average Exponential"]}
          </script>
        </div></body></html>
        """
        view.loadHTMLString(html, baseURL: URL(string: "https://www.tradingview.com/"))
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var loadedKey: String?

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            // Allow only the official widget and provider-owned subresources.
            // No custom scheme, arbitrary external navigation, or JS bridge.
            guard url.scheme == "https",
                  let host = url.host?.lowercased(),
                  host == "tradingview.com" || host.hasSuffix(".tradingview.com") else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}

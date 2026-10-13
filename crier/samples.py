from .models import Snapshot


def sample(scenario):
    base = dict(account="sample", order_id="sample", symbol="SPY261016C00600000", category="US_OPTION",
                side="BUY", intent="OPEN", cumulative_qty="4", average_price="1.25",
                occurred_at="2026-10-13T14:42:18Z", status="FILLED")
    scenarios = {"option_buy": {}, "option_sell": {"side": "SELL", "intent": "CLOSE", "average_price": "1.62", "cumulative_qty": "2"},
                 "partial": {"status": "PARTIAL", "cumulative_qty": "1"},
                 "stock_buy": {"symbol": "AAPL", "category": "US_STOCK", "cumulative_qty": "10", "average_price": "230.50"}}
    snap = Snapshot(**(base | scenarios[scenario]))
    fill = snap.model_dump(mode="json")
    for key in ("account", "order_id", "average_price"): fill.pop(key)
    return fill | {"quantity": str(snap.cumulative_qty), "price": str(snap.average_price),
                   "contract": snap.contract, "expiration": snap.expiration, "reference": "SAMPLE"}

"""Public rendering contains no broker account IDs or broker order IDs."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from .models import Settings, OCC, number


def render(fill: dict, settings: Settings) -> dict:
    qty = number(fill["quantity"])
    raw_price = Decimal(fill["price"])
    digits = min(8, max(2, -raw_price.as_tuple().exponent))
    price = f"{raw_price:.{digits}f}"
    side = fill["side"]
    stamp = datetime.fromisoformat(fill["occurred_at"].replace("Z", "+00:00"))
    time = stamp.astimezone(ZoneInfo(settings.timezone)).strftime("%b %d, %Y · %I:%M:%S %p %Z")
    expiry = fill.get("expiration")
    title = fill["contract"] + (f" · {expiry}" if expiry else "")
    unit = "contracts" if expiry else "shares"
    amount = f"{qty}× " if settings.show_quantity else ""
    action = "Bought" if side == "BUY" else "Sold"
    headline = f"{action} · Filled {amount}@ ${price}"
    status = "Partial order fill" if fill["status"] == "PARTIAL" else "Order filled"
    if settings.format == "homebrew":
        # Formatting adapted from the user's AlertBot_CardKit/cards.py.
        # Preserve the full year and never fabricate its optional P/L/peak ledger.
        short_exp = datetime.strptime(expiry, "%Y-%m-%d").strftime("%m-%d-%Y") if expiry else ""
        icon = "🟢" if side == "BUY" else "📤"
        header = f"{icon} **{fill['contract']}**" + (f" {short_exp}" if expiry else "") + f" · {settings.display_name}"
        fill_label = "Filled" if side == "BUY" else "SELL FILLED"
        amount = (qty + ("×" if expiry else " shares") + " @ ") if settings.show_quantity else "@ "
        lines = [header, f"{fill_label} **{amount}${price}**"]
        if side == "SELL":
            ledger = f"{' exit':<7}{'price':>10}" + (f"{'qty':>8}" if settings.show_quantity else "")
            ledger += "\n" + "-" * (25 if settings.show_quantity else 17)
            ledger += f"\n{'sell':<7}{('$' + price):>10}" + (f"{qty:>8}" if settings.show_quantity else "")
            lines.append(f"```\n{ledger}\n```")
        meta = status + " · Webull " + fill.get("environment", "sandbox")
        if settings.show_time: meta += " · " + time
        lines.extend([meta, "Ref " + fill.get("reference", "preview")])
        return {"content": "\n".join(lines), "allowed_mentions": {"parse": []}}
    if settings.format == "echo":
        if fill.get("intent") != "OPEN" or side != "BUY" or not expiry:
            raise ValueError("Echo template currently supports verified option buy-to-open fills only; use Homebrew or plain text for other events")
        m = OCC.fullmatch(fill["symbol"])
        exp = datetime.strptime(expiry, "%Y-%m-%d").strftime("%m/%d/%Y")
        content = f"BTO {qty} {m[1]} {number(Decimal(m[4]) / 1000)}{m[3]} {exp} @ {price}"
        return {"content": content, "allowed_mentions": {"parse": []}}
    lines = [title, f"{settings.display_name} · {headline}", status]
    if settings.show_time: lines.append(time)
    if settings.format == "text":
        return {"content": "\n".join(lines), "allowed_mentions": {"parse": []}}
    # A compact ledger follows Homebrew's visual grammar, without fabricated P/L.
    ledger = f"{'fill':<7}{'price':>10}" + (f"{'qty':>8}" if settings.show_quantity else "")
    ledger += f"\n{'buy' if side == 'BUY' else 'sell':<7}{('$' + price):>10}" + (f"{qty:>8}" if settings.show_quantity else "")
    fields = [{"name": "Execution", "value": f"```text\n{ledger}\n```", "inline": False},
              {"name": "Status", "value": status, "inline": True}]
    if settings.show_quantity:
        fields.append({"name": "Order filled so far", "value": f"{number(fill['cumulative_qty'])} {unit}", "inline": True})
    if settings.show_time: fields.append({"name": "Time", "value": time, "inline": False})
    return {"embeds": [{"author": {"name": f"Sentinel Crier · {settings.display_name}"},
        "title": title, "description": headline, "color": int(settings.color[1:], 16),
        "fields": fields, "footer": {"text": "Webull · " + fill.get("environment", "sandbox").title() + " · " + fill.get("reference", "preview")}}],
        "allowed_mentions": {"parse": []}}

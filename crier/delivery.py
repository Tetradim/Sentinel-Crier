import math
import re
import httpx
from .store import Store
from .component_health import emit


def validate_webhook(url):
    if not re.fullmatch(r"https://discord\.com/api/webhooks/\d+/[\w.-]+", url):
        raise ValueError("Use an HTTPS discord.com webhook URL without query parameters")
    return url


def deliver_once(store: Store, webhook: str, client: httpx.Client, job_id=None, *, observe=None):
    validate_webhook(webhook)
    job = store.claim(job_id)
    if not job:
        if observe:
            with store.connect() as db:
                states={r[0] for r in db.execute("SELECT DISTINCT status FROM outbox WHERE status NOT IN ('sent','closed')")}
            state,reason='idle','no_work'
            if states & {'uncertain','sending'}: state,reason='blocked','uncertain'
            elif states & {'failed','review'}: state,reason='blocked','rejected'
            elif states: state,reason='degraded','waiting_retry'
            emit(observe,'discord',state,reason)
        return False
    state,reason='blocked','uncertain'
    try:
        response = client.post(webhook + "?wait=true", json=job["payload"], timeout=15, follow_redirects=False)
        if response.status_code == 429:
            try: delay = float(response.json().get("retry_after", 5))
            except (ValueError, TypeError, AttributeError): delay = 5
            if not math.isfinite(delay): delay = 60
            store.throttle(max(1, delay))
            store.complete(job["id"], "pending", "Discord rate limit", delay=max(1, delay))
            state,reason='degraded','rate_limited'
        elif response.status_code == 200:
            try:
                message_id = str(response.json()["id"])
                if not message_id.isdigit(): raise ValueError("Invalid message ID")
            except (ValueError, KeyError, TypeError):
                store.complete(job["id"], "uncertain", "Discord accepted the request without a usable message ID")
            else:
                store.complete(job["id"], "sent", message_id=message_id)
                state,reason='healthy','delivered'
        elif 400 <= response.status_code < 500:
            store.complete(job["id"], "failed", f"Discord rejected request: HTTP {response.status_code}")
            state,reason='blocked','rejected'
        else:
            store.complete(job["id"], "uncertain", f"Discord response ambiguous: HTTP {response.status_code}")
    except httpx.ConnectError:
        store.complete(job["id"], "pending" if job["attempts"] < 4 else "failed", "Connection failed", delay=30)
        state,reason='degraded','connection_failed'
    except httpx.HTTPError:
        # Discord webhooks have no general idempotency key. Never blindly retry a possibly successful send.
        store.complete(job["id"], "uncertain", "Delivery could not be confirmed; check Discord")
    emit(observe,'discord',state,reason)
    return True

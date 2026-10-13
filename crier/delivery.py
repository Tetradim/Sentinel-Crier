import math
import re
import httpx
from .store import Store


def validate_webhook(url):
    if not re.fullmatch(r"https://discord\.com/api/webhooks/\d+/[\w.-]+", url):
        raise ValueError("Use an HTTPS discord.com webhook URL without query parameters")
    return url


def deliver_once(store: Store, webhook: str, client: httpx.Client):
    validate_webhook(webhook)
    job = store.claim()
    if not job: return False
    try:
        response = client.post(webhook + "?wait=true", json=job["payload"], timeout=15, follow_redirects=False)
        if response.status_code == 429:
            try: delay = float(response.json().get("retry_after", 5))
            except (ValueError, TypeError, AttributeError): delay = 5
            if not math.isfinite(delay): delay = 60
            store.throttle(max(1, delay))
            store.complete(job["id"], "pending", "Discord rate limit", delay=max(1, delay))
        elif response.status_code == 200:
            try:
                message_id = str(response.json()["id"])
                if not message_id.isdigit(): raise ValueError("Invalid message ID")
            except (ValueError, KeyError, TypeError):
                store.complete(job["id"], "uncertain", "Discord accepted the request without a usable message ID")
            else: store.complete(job["id"], "sent", message_id=message_id)
        elif 400 <= response.status_code < 500:
            store.complete(job["id"], "failed", f"Discord rejected request: HTTP {response.status_code}")
        else:
            store.complete(job["id"], "uncertain", f"Discord response ambiguous: HTTP {response.status_code}")
    except httpx.ConnectError:
        store.complete(job["id"], "pending" if job["attempts"] < 4 else "failed", "Connection failed", delay=30)
    except httpx.HTTPError:
        # Discord webhooks have no general idempotency key. Never blindly retry a possibly successful send.
        store.complete(job["id"], "uncertain", "Delivery could not be confirmed; check Discord")
    return True

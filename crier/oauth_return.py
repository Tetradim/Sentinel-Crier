"""Preparation only: no registered handler, login, redemption or credential installation.

Only an in-memory flow from the initiating authenticated session can accept a
return. Integrators must invalidate it on logout/session changes, use a trusted
clock, and separately configure and wire login and credential installation.
"""

from dataclasses import dataclass
import math
import re
import threading


_PREFIX = 'sentinelcrier://oauth/complete?flow='
_FLOW = re.compile(r'[A-Za-z0-9_-]{43}', re.ASCII)


def parse_oauth_return(uri: str) -> str | None:
    """Match raw text, never URL-normalized or percent-decoded input."""
    if not isinstance(uri, str) or len(uri) != len(_PREFIX) + 43:
        return None
    if not uri.startswith(_PREFIX):
        return None
    flow = uri[len(_PREFIX):]
    return flow if _FLOW.fullmatch(flow) else None


@dataclass(frozen=True)
class OAuthReturnContext:
    owner: str
    provider: str
    environment: str
    purpose: str

    def __post_init__(self):
        if (not isinstance(self.owner, str) or not self.owner.strip()
                or len(self.owner) > 256
                or self.provider not in ('alpaca', 'discord')
                or self.environment not in ('paper', 'live')
                or self.purpose not in ('alerts', 'trade')
                or (self.provider == 'discord' and self.purpose != 'alerts')):
            raise ValueError('Invalid local OAuth context')


class PendingOAuthReturn:
    """One-use, memory-only pending return. All times use the caller's same clock.

    Context is captured locally at flow creation; a URI cannot select it. A
    successful match is only permission to attempt authenticated redemption,
    never permission to enable execution or publishing.
    """

    def __init__(self, flow: str, context: OAuthReturnContext, *, expires_at: float):
        if (not isinstance(flow, str) or not _FLOW.fullmatch(flow)
                or not isinstance(context, OAuthReturnContext)
                or not math.isfinite(expires_at)):
            raise ValueError('Invalid pending OAuth return')
        self._flow = flow
        self._context = context
        self._expires_at = expires_at
        self._active = True
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._active = False

    def cancel(self) -> None:
        self.invalidate()

    def match_return(self, uri: str, expected_flow: str,
                     expected_context: OAuthReturnContext, *, now: float) -> OAuthReturnContext | None:
        with self._lock:
            if not self._active:
                return None
            if not math.isfinite(now) or now >= self._expires_at:
                self._active = False
                return None
            if (expected_flow != self._flow or expected_context != self._context
                    or parse_oauth_return(uri) != self._flow):
                return None
            self._active = False
            return self._context

    @staticmethod
    def match_pending(pending: 'PendingOAuthReturn | None', uri: str, expected_flow: str,
                      expected_context: OAuthReturnContext, *, now: float) -> OAuthReturnContext | None:
        """A process restart without pending state always rejects a return."""
        return None if pending is None else pending.match_return(uri, expected_flow, expected_context, now=now)

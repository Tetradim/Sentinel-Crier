"""Ephemeral setup evidence; never grants broker execution permission."""
from dataclasses import dataclass


@dataclass
class SetupProgress:
    scope: tuple | None = None
    revision: str = ''
    generation: int = 0
    configured: bool = False
    enabled: bool = False
    paused: bool = False
    previewed: bool = False
    test_state: str = 'not requested'

    @property
    def token(self):
        return self.generation, self.scope, self.revision

    def invalidate(self):
        self.generation += 1
        self.previewed = False
        self.test_state = 'not requested'

    def account(self, scope):
        if scope != self.scope:
            self.invalidate()
            self.scope = scope
            self.revision = ''
            self.configured = self.enabled = self.paused = False

    def destination(self, revision, *, configured, enabled, paused):
        if not self.scope:
            return
        if revision != self.revision or configured != self.configured:
            self.invalidate()
        self.revision, self.configured = revision, configured
        self.enabled, self.paused = enabled, paused

    def preview(self, token):
        if self.scope and token == self.token:
            self.previewed = True

    def test(self, token, status):
        if self.scope and token == self.token:
            self.test_state = status if status in ('delivered', 'pending', 'uncertain', 'failed', 'review', 'closed', 'sending') else 'unverified'

    @property
    def can_publish(self):
        return bool(self.scope and self.configured)

    @property
    def message(self):
        if not self.scope:
            return '1. Connect to verify the account. Saved settings are not a current connection.'
        if not self.configured:
            return '2. Save a Discord destination. Delivery remains separate from account verification.'
        state = 'Delivery paused in saved settings.' if self.paused else 'Delivery enabled.' if self.enabled else 'Delivery disabled; enable explicitly when ready.'
        if self.test_state == 'uncertain':
            return state + ' Test acknowledgement uncertain; inspect Discord before retrying.'
        if self.test_state != 'not requested':
            return state + f' Test: {self.test_state}. A test is synthetic, never a broker fill.'
        if not self.previewed:
            return state + ' 3. Preview the saved format, then optionally send a labeled test.'
        return state + ' Preview checked. 4. Optionally send a labeled test; no test has been requested.'

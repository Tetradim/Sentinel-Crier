"""Journey composition preserves DesktopApp callbacks and lifecycle fencing."""
from types import SimpleNamespace
from crier.desktop_journeys import DesktopJourneys
import pytest


class Value:
    def __init__(self, value=''): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


def coordinator(app):
    return DesktopJourneys(app)


@pytest.mark.parametrize('fence', ['epoch', 'closing', 'stop'])
def test_deferred_pairing_reconnect_rechecks_stop_fence(fence):
    queued, submitted = [], []
    app = SimpleNamespace(action_epoch=0, closing=False, connected=False,
        stopping_all=lambda: False, root=SimpleNamespace(after=lambda delay, fn: queued.append(fn)),
        pairing=Value(), service=Value('relay'), host_environment=Value('paper'), invitation=Value(), share=Value(),
        submit=lambda *args, **kw: submitted.append((args, kw)), connect=lambda: submitted.append('connect'))
    journey = coordinator(app)
    journey.quick_connect('host')
    submitted[0][1]['callback']({'pair': {'url':'relay', 'environment':'paper'}})
    assert len(queued) == 1
    if fence == 'epoch': app.action_epoch += 1
    elif fence == 'closing': app.closing = True
    else: app.stopping_all = lambda: True
    queued[0]()
    assert 'connect' not in submitted


def test_purpose_change_requires_disconnect_without_dispatching_worker():
    app = SimpleNamespace(connected=True, provider_purpose='alerts', notice=Value())
    coordinator(app).choose_purpose('trade')
    assert app.provider_purpose == 'alerts'
    assert 'Disconnect' in app.notice.get()


@pytest.mark.parametrize('purpose,page,provider', [('alerts','alerts','alerts'), ('trade','setup','trade'), ('follow','setup','trade')])
def test_purpose_changes_only_navigation_and_signin_purpose(purpose,page,provider):
    selected=[]
    app=SimpleNamespace(connected=False,provider_purpose='',notice=Value(),alerts_tab='alerts',setup_tab='setup',tabs=SimpleNamespace(select=selected.append))
    coordinator(app).choose_purpose(purpose)
    assert selected == [page]
    assert app.provider_purpose == provider

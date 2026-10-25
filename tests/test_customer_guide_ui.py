from concurrent.futures import Future
import gc
import tkinter as tk
import pytest
from crier.desktop import DesktopApp


class Worker:
    def __init__(self): self.calls=[]
    def call(self,method,*args,**kwargs):
        self.calls.append((method,args,kwargs)); return Future()


@pytest.fixture(scope='module')
def root():
    try: window=tk.Tk()
    except tk.TclError as exc: pytest.skip(f'Tk unavailable: {exc}')
    window.withdraw(); yield window
    window.destroy(); gc.collect()


@pytest.fixture
def app(root):
    window=tk.Toplevel(root); window.withdraw(); app=DesktopApp(window,Worker())
    yield app
    window.destroy(); gc.collect()


def test_optional_guide_switches_journey_without_any_worker_calls(app):
    dialog=app.open_practice(); dialog.window.withdraw()
    assert 'Connect a paper account' in dialog.body.get('1.0','end')
    dialog.selector.current(2); dialog.selector.event_generate('<<ComboboxSelected>>')
    assert 'Join a paper host' in dialog.body.get('1.0','end')
    assert not app.worker.calls and not app.connected
    assert dialog.body['state']=='disabled'
    assert dialog.body.bind('<Tab>') and dialog.body.bind('<Shift-Tab>')
    assert dialog.window.bind('<Escape>') and app.root.bind('<F1>')


def test_reopening_reuses_window_and_support_only_opens_approved_route(app,monkeypatch):
    opened=[]; monkeypatch.setattr('crier.desktop_practice.webbrowser.open',lambda url:opened.append(url))
    dialog=app.open_practice(); dialog.window.withdraw()
    assert app.open_practice() is dialog
    dialog.support.invoke()
    assert opened==['https://github.com/Tetradim/Sentinel-Crier/issues']
    assert not app.worker.calls
    assert 'API keys' in dialog.body.get('1.0','end')


def test_existing_readonly_evidence_panels_allow_tab_navigation(app):
    for widget in (app.delivery_details,app.diagnostic_text):
        assert widget.bind('<Tab>') and widget.bind('<Shift-Tab>')

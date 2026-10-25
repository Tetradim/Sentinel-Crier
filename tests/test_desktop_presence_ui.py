from concurrent.futures import Future
import gc
import tkinter as tk
import pytest

from crier.desktop import DesktopApp
from crier.desktop_presence import Presence
from test_desktop_presence import Tray, startup


class Worker:
    def __init__(self): self.calls=[]; self.closed=False
    def call(self, method, *args, **kwargs):
        future=Future(); self.calls.append((method,args,kwargs,future)); return future
    def close(self): self.closed=True


@pytest.fixture(scope='module')
def tk_root(desktop_tk_root):
    return desktop_tk_root


@pytest.fixture
def app(tmp_path,tk_root):
    root=tk.Toplevel(tk_root); root.withdraw()
    registration,_=startup(tmp_path)
    presence=Presence(tmp_path,startup=registration,tray_factory=Tray)
    worker=Worker()
    desktop=DesktopApp(root,worker,presence=presence)
    yield desktop
    presence.stop()
    try: root.destroy()
    except tk.TclError: pass
    gc.collect()


def test_close_hides_only_after_opt_in_and_ready_tray_without_disconnect(app):
    app.tray_choice.set(True); app.toggle_tray()
    app.close()
    assert app.root.state()=='withdrawn' and not app.closing
    assert not app.worker.calls
    app.presence.tray.send('show'); app.poll_presence()
    assert app.root.state()=='normal'


def test_disabling_or_losing_tray_restores_window(app):
    app.tray_choice.set(True); app.toggle_tray(); app.close()
    app.presence.tray.alive=False; app.poll_presence()
    assert app.root.state()=='normal' and not app.presence.tray_ready
    app.tray_choice.set(False); app.toggle_tray()
    assert app.root.state()=='normal'


def test_tray_pause_uses_existing_worker_settings_and_never_enables(app):
    app.tray_choice.set(True); app.toggle_tray()
    app.presence.tray.send('pause'); app.poll_presence()
    assert app.worker.calls[-1][:2]==('settings',({'enabled':False},))
    assert all(args!=({'enabled':True},) for _,args,_,_ in app.worker.calls)


def test_quit_waits_for_disconnect_and_stops_tray_on_success(app):
    app.tray_choice.set(True); app.toggle_tray(); tray=app.presence.tray
    app.presence.tray.send('quit'); app.poll_presence()
    assert app.closing and app.worker.calls[-1][0]=='disconnect'
    assert not tray.stopped and not app.worker.closed
    app.worker.calls[-1][3].set_result(None)
    # Invoke the scheduled shutdown callback without sleeping or broker calls.
    callbacks=app.root.tk.call('after','info')
    for token in callbacks:
        script=app.root.tk.call('after','info',token)[0]
        if 'finish' in script:
            app.root.tk.call('after','cancel',token)
            app.root.tk.eval(script)
            break
    assert tray.stopped and app.worker.closed


def test_opt_in_never_connects_and_startup_checkbox_only_registers(app):
    app.startup_choice.set(True); app.toggle_startup()
    assert app.presence.startup.enabled and not app.worker.calls
    assert not app.connected and app.latest=={}


def test_cancelled_quit_preserves_running_tray(app,monkeypatch):
    app.tray_choice.set(True); app.toggle_tray(); app.close(); app.connected=True
    monkeypatch.setattr('crier.desktop.messagebox.askokcancel',lambda *a,**k:False)
    app.presence.tray.send('quit'); app.poll_presence()
    assert app.root.state()=='normal' and not app.closing and app.presence.tray_ready
    assert not app.worker.calls


def test_startup_with_saved_tray_never_connects_or_changes_execution(tmp_path,tk_root):
    (tmp_path/'desktop-presence.json').write_text('{"tray":true}')
    root=tk.Toplevel(tk_root)
    presence=Presence(tmp_path,tray_factory=Tray); worker=Worker()
    try:
        desktop=DesktopApp(root,worker,presence=presence,startup=True)
        assert root.state()=='withdrawn' and presence.tray_ready
        assert not desktop.connected and not worker.calls
    finally:
        presence.stop(); root.destroy(); gc.collect()


def test_startup_with_unavailable_tray_keeps_window_visible(tmp_path,tk_root):
    class Unavailable(Tray):
        def start(self): return False
    (tmp_path/'desktop-presence.json').write_text('{"tray":true}')
    root=tk.Toplevel(tk_root)
    presence=Presence(tmp_path,tray_factory=Unavailable); worker=Worker()
    try:
        desktop=DesktopApp(root,worker,presence=presence,startup=True)
        assert root.state()=='normal' and not presence.tray_ready
        assert 'visible' in desktop.notice.get() and not worker.calls
    finally:
        presence.stop(); root.destroy(); gc.collect()

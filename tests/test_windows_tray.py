"""Native-thread lifecycle without creating a real notification-area icon."""
import sys
import threading
from types import SimpleNamespace
from crier import windows_tray


def fake_native(monkeypatch, gate=None):
    class Icon:
        def __init__(self, *args):
            self.visible=False; self.running=False; self.stopped=threading.Event()
        def run(self, setup):
            if gate: gate.wait(2)
            self.running=True; setup(self); self.stopped.wait(2)
        def stop(self):
            if self.running:
                self.visible=False; self.stopped.set()
    monkeypatch.setitem(sys.modules,'pystray',SimpleNamespace(Icon=Icon,Menu=lambda *items:items,MenuItem=lambda *args,**kwargs:args))
    draw=SimpleNamespace(ellipse=lambda *a,**k:None,line=lambda *a,**k:None)
    monkeypatch.setitem(sys.modules,'PIL',SimpleNamespace(Image=SimpleNamespace(new=lambda *a:object()),ImageDraw=SimpleNamespace(Draw=lambda _:draw)))
    monkeypatch.setattr(windows_tray,'sys',SimpleNamespace(platform='win32'))


def test_ready_then_stop_terminates_tray_worker(monkeypatch):
    fake_native(monkeypatch)
    tray=windows_tray.WindowsTray(lambda _:None)
    assert tray.start() and tray.icon.visible
    tray.stop(); assert not tray.alive and not tray.icon.visible


def test_stop_before_late_native_setup_never_leaves_an_orphan_icon(monkeypatch):
    gate=threading.Event(); fake_native(monkeypatch,gate)
    tray=windows_tray.WindowsTray(lambda _:None); tray.thread.start()
    stop=threading.Thread(target=tray.stop); stop.start()
    try:
        assert tray.stopping.wait(1)
    finally:
        gate.set(); stop.join(3); tray.thread.join(3)
    assert not tray.alive and not tray.icon.visible

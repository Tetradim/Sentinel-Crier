import json
from pathlib import Path
import pytest

from crier.desktop_presence import Presence, StartupRegistration


class Registry:
    def __init__(self): self.value = None; self.writes = []
    def get(self): return self.value
    def set(self, value): self.writes.append(value); self.value = value
    def delete(self): self.writes.append(None); self.value = None


class Tray:
    def __init__(self, send): self.send = send; self.alive = False; self.stopped = False
    def start(self): self.alive = True; return True
    def stop(self): self.stopped = True; self.alive = False


def startup(tmp_path):
    executable = tmp_path/'Crier app.exe'; executable.touch()
    registry = Registry()
    return StartupRegistration(executable, frozen=True, platform='win32', registry=registry), registry


def test_default_off_does_not_write_or_create_an_icon(tmp_path):
    registration, registry = startup(tmp_path)
    def unexpected(_): pytest.fail('Default startup must not create tray')
    presence = Presence(tmp_path, startup=registration, tray_factory=unexpected)
    presence.start()
    assert not presence.tray_enabled and not presence.tray_ready
    assert not registration.enabled and registry.writes == []
    assert not (tmp_path/'desktop-presence.json').exists()


@pytest.mark.parametrize('contents', ['{broken', '[]', '{"tray": "true"}', '{"tray": true, "extra": "secret"}'])
def test_invalid_preferences_fail_visible_and_do_not_rewrite_evidence(tmp_path, contents):
    path = tmp_path/'desktop-presence.json'; path.write_text(contents)
    presence = Presence(tmp_path)
    assert not presence.tray_enabled and presence.error
    assert path.read_text() == contents


def test_only_explicit_startup_registration_writes_current_user_value(tmp_path):
    registration, registry = startup(tmp_path)
    assert registration.available and not registration.enabled and not registry.writes
    registration.set_enabled(True)
    assert registration.enabled and registry.value == f'"{tmp_path / "Crier app.exe"}" --startup'
    assert 'secret' not in registry.value
    registration.set_enabled(False)
    assert not registration.enabled and registry.value is None


@pytest.mark.parametrize('frozen,platform', [(False,'win32'),(True,'linux')])
def test_startup_is_unavailable_for_source_or_other_platform(tmp_path, frozen, platform):
    registry = Registry()
    registration = StartupRegistration(Path(__file__), frozen=frozen, platform=platform, registry=registry)
    assert not registration.available
    with pytest.raises(ValueError): registration.set_enabled(True)
    assert not registry.writes


def test_disabling_does_not_delete_a_different_program_registration(tmp_path):
    registration, registry = startup(tmp_path); registry.value = 'another app'
    with pytest.raises(ValueError, match='different'): registration.set_enabled(False)
    assert registry.value == 'another app' and not registry.writes


def test_ready_tray_persists_only_preference_and_queues_fixed_actions(tmp_path):
    presence = Presence(tmp_path, tray_factory=Tray)
    presence.set_tray(True)
    assert presence.tray_ready and presence.tray_enabled
    tray = presence.tray
    for action in ['show','pause','enable','quit']: tray.send(action)
    assert presence.poll() == ['show','pause','quit']
    assert json.loads((tmp_path/'desktop-presence.json').read_text()) == {'tray':True}
    presence.set_tray(False)
    assert tray.stopped and not presence.tray_ready


def test_failed_or_lost_tray_never_authorizes_hiding(tmp_path):
    class Failed(Tray):
        def start(self): return False
    presence = Presence(tmp_path, tray_factory=Failed)
    with pytest.raises(ValueError, match='tray'): presence.set_tray(True)
    assert not presence.tray_enabled and not presence.tray_ready
    presence = Presence(tmp_path, tray_factory=Tray); presence.set_tray(True)
    presence.tray.alive = False
    assert presence.poll() == ['show'] and not presence.tray_ready and presence.error
    presence.stop()


def test_saved_opt_in_requires_successful_icon_on_each_launch(tmp_path):
    (tmp_path/'desktop-presence.json').write_text('{"tray":true}')
    presence = Presence(tmp_path, tray_factory=Tray)
    assert presence.tray_enabled and not presence.tray_ready
    presence.start(); assert presence.tray_ready
    tray = presence.tray; presence.stop(); assert tray.stopped


def test_preference_write_failure_stops_new_icon(tmp_path, monkeypatch):
    presence = Presence(tmp_path, tray_factory=Tray)
    monkeypatch.setattr('crier.desktop_presence.os.replace', lambda *args: (_ for _ in ()).throw(OSError('full')))
    with pytest.raises(ValueError): presence.set_tray(True)
    assert not presence.tray_ready and not presence.tray_enabled


def test_tray_cleanup_failure_cannot_leave_the_window_hideable(tmp_path):
    class BrokenStop(Tray):
        def stop(self): raise OSError('native cleanup failed')
    presence=Presence(tmp_path,tray_factory=BrokenStop); presence.set_tray(True)
    presence.stop()
    assert not presence.tray_ready and presence.error

import json
from pathlib import Path

import pytest


def test_version_handles_absent_packaged_metadata_without_crashing(monkeypatch):
    from crier.desktop_updates import current_version
    import crier.error_log
    monkeypatch.setattr(crier.error_log,'read_build_info',lambda path:None)
    monkeypatch.setattr('importlib.metadata.version',lambda name:'0.3.0')
    assert current_version()=='0.3.0'
    monkeypatch.setattr('sys.frozen',True,raising=False)
    with pytest.raises(ValueError):current_version()


def test_disabled_update_policy_is_clear_and_offline(tmp_path):
    from crier.desktop_updates import DesktopUpdates
    manager=DesktopUpdates(tmp_path,'0.2.0',policy=dict(schema=1,enabled=False,repository='Tetradim/Sentinel-Crier',channel='stable',public_keys={},publisher_thumbprints=[]))
    assert manager.check()['status']=='unconfigured'
    assert manager.state['status']=='unconfigured'
    with pytest.raises(ValueError):manager.prepare()


def test_controller_never_launches_before_closed_worker_and_backup(tmp_path,monkeypatch):
    from crier import desktop_updates
    events=[]
    class Client:
        release={'version':'0.3.0','notes':'synthetic'}
        def __init__(self,*a,**kw):pass
        def check(self):return {'status':'available','version':'0.3.0','notes':'synthetic'}
        def download(self):events.append('download');return tmp_path/'installer.exe'
    monkeypatch.setattr(desktop_updates,'UpdateClient',Client)
    monkeypatch.setattr(desktop_updates,'prepare_install',lambda *a,**kw:(events.append('prepare') or {'command':['synthetic'],'backup':'backup'}))
    manager=desktop_updates.DesktopUpdates(tmp_path/'profile','0.2.0',policy={'publisher_thumbprints':[]})
    assert manager.check()['status']=='available'
    assert manager.download()['status']=='ready'
    with pytest.raises(ValueError):manager.prepare()
    assert events==['download']
    manager.prepare(worker_closed=True)
    assert events==['download','prepare']


def test_profile_gate_refuses_newer_data_before_constructing_worker(tmp_path,monkeypatch):
    from crier import desktop
    marker=tmp_path/'profile-format.json'
    marker.write_text(json.dumps({'schema':1,'generation':99}))
    notices=[]
    monkeypatch.setattr(desktop,'data_directory',lambda:tmp_path)
    monkeypatch.setattr(desktop,'DesktopWorker',lambda *a:pytest.fail('worker must not open incompatible data'))
    monkeypatch.setattr(desktop,'show_profile_error',lambda:notices.append('blocked'),raising=False)
    monkeypatch.setattr('sys.argv',['crier-desktop'])
    with pytest.raises(SystemExit):desktop.main()
    assert notices==['blocked']
    assert json.loads(marker.read_text())['generation']==99


def test_ui_update_handoff_occurs_after_worker_shutdown():
    from concurrent.futures import Future
    from types import SimpleNamespace
    from crier.desktop import DesktopApp
    events=[]
    def drain(method):
        events.append(method);future=Future();future.set_result(None);return future
    app=DesktopApp.__new__(DesktopApp)
    app.closing=False;app.connected=False;app.presence=None;app.update_requested=True
    app.notice=SimpleNamespace(set=lambda *a:None)
    app.root=SimpleNamespace(destroy=lambda:events.append('destroy'),after=lambda *a:None)
    app.worker=SimpleNamespace(call=drain,close=lambda:events.append('worker_closed'))
    app.finish_update=lambda:events.append('handoff')
    app.close(quit=True,update=True)
    assert events==['disconnect','worker_closed','handoff']


def test_failed_update_shutdown_does_not_install_on_later_quit(monkeypatch):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from crier import desktop
    events=[]
    def drain(method):
        future=Future()
        if not events:future.set_exception(OSError('synthetic shutdown'))
        else:future.set_result(None)
        events.append(method)
        return future
    app=desktop.DesktopApp.__new__(desktop.DesktopApp)
    app.closing=False;app.connected=True;app.presence=None;app.update_requested=False
    app.updater=SimpleNamespace(state={'status':'ready'})
    app.root=SimpleNamespace(after=lambda *a:None,destroy=lambda:events.append('destroy'))
    app.notice=SimpleNamespace(set=lambda *a:None)
    app.worker=SimpleNamespace(call=drain,close=lambda:events.append('closed'))
    app.finish_update=lambda:pytest.fail('canceled/failed shutdown must not install')
    monkeypatch.setattr(desktop.messagebox,'askokcancel',lambda *a,**kw:True)
    app.update_action()
    assert not app.closing and not app.update_requested
    app.close(quit=True)
    assert events==['disconnect','disconnect','closed','destroy']

from concurrent.futures import Future
from types import SimpleNamespace


def app_fixture():
    from crier.desktop import DesktopApp
    from crier.startup_notice import StartupNotice
    app=DesktopApp.__new__(DesktopApp)
    events=[]
    app.closing=False;app.update_future=None;app.startup_notice=StartupNotice()
    app.tabs=None
    app.updater=SimpleNamespace(state={'status':'available'},check=lambda:(events.append('check') or {'status':'available','version':'0.3.1','notes':'Changes'}))
    app.startup_update_text=SimpleNamespace(set=lambda value:events.append(value))
    app.update_banner=SimpleNamespace(pack=lambda **kw:events.append('show'),pack_forget=lambda:events.append('dismiss'))
    app.root=SimpleNamespace(deiconify=lambda:(_ for _ in ()).throw(AssertionError('must not reveal hidden tray startup')))
    app.render_update_result=lambda value:events.append('manual_ready')
    app.run_update_job=lambda operation,callback,**kw:callback(operation())
    return app,events


def test_startup_checks_once_without_installing_or_showing_hidden_window():
    app,events=app_fixture()
    app.check_startup_updates();app.check_startup_updates()
    assert events.count('check')==1 and events.count('show')==1
    app.dismiss_startup_update()
    assert app.updater.state['status']=='available'
    assert events[-1]=='dismiss'


def test_late_startup_callback_is_ignored_after_close_or_dismissal():
    for close in (True,False):
        app,events=app_fixture();callbacks=[]
        app.run_update_job=lambda op,cb,**kw:callbacks.append(cb)
        app.check_startup_updates()
        if close:app.startup_notice.close()
        else:app.dismiss_startup_update()
        callbacks[0]({'status':'available','version':'0.3.1','notes':'Changes'})
        assert 'show' not in events and 'manual_ready' not in events


def test_startup_does_not_queue_behind_an_existing_manual_update():
    app,events=app_fixture();app.update_future=Future()
    app.check_startup_updates()
    assert 'check' not in events


def test_support_context_exposes_only_public_build_information(monkeypatch):
    from crier import customer_support
    monkeypatch.setattr(customer_support,'current_version',lambda:'0.3.1')
    monkeypatch.setattr(customer_support,'read_build_info',lambda _: {'commit':'a'*40,'private':'DO-NOT-EXPORT'})
    row=customer_support.support_details()
    assert row['version']=='0.3.1' and row['source']=='a'*40
    assert 'DO-NOT-EXPORT' not in str(row)
    assert row['url']=='https://github.com/Tetradim/Sentinel-Crier/issues'


def test_connection_test_button_does_not_queue_duplicate_probes():
    from crier.desktop import DesktopApp
    app=DesktopApp.__new__(DesktopApp);calls=[];future=Future()
    app.closing=False;app.pending=[]
    app.notice=SimpleNamespace(set=lambda value:None)
    app.worker=SimpleNamespace(call=lambda method:(calls.append(method) or future))
    app.test_connection();app.test_connection()
    assert calls==['connection_test'] and len(app.pending)==1

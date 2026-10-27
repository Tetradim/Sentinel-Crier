import json
import threading
import time
import zipfile
from uuid import uuid4

from crier.error_log import ErrorLog, emit_error, read_build_info


def test_secret_messages_and_unknown_context_never_enter_logs_or_bundle(tmp_path):
    log=ErrorLog(tmp_path/'logs')
    try:
        try: raise RuntimeError('Bearer SECRET_KEY webhook=https://discord.test/private')
        except RuntimeError as exc:
            emit_error(log,'broker.failed',exc,trade_id=str(uuid4()),token='SECRET_KEY')
        assert log.flush()
        (tmp_path/'logs'/'credentials.secret').write_text('SECRET_KEY')
        target=tmp_path/'support.zip'
        log.export(target)
        with zipfile.ZipFile(target) as archive:
            assert sorted(archive.namelist())==['diagnostics/error-log.jsonl','manifest.json']
            content=''.join(archive.read(name).decode() for name in archive.namelist())
            assert 'SECRET_KEY' not in content and 'discord.test' not in content
            record=json.loads(archive.read('diagnostics/error-log.jsonl').splitlines()[0])
            assert record['exception_type']=='RuntimeError'
            assert record['stack'][-1]['file']=='test_error_log.py'
            assert record['stack'][-1]['line']>0
    finally: log.close()


def test_rotation_is_bounded_and_does_not_touch_neighbor_files(tmp_path):
    folder=tmp_path/'logs';folder.mkdir();other=folder/'keep.secret';other.write_text('private')
    log=ErrorLog(folder,max_bytes=512,backups=2)
    try:
        for i in range(40):log.event('desktop.event_'+str(i))
        assert log.flush()
        assert len(list(folder.glob('error-log.jsonl*')))<=3
        assert len(list(folder.glob('error-log.jsonl*')))>1
        assert other.read_text()=='private'
    finally: log.close()


def test_full_queue_drops_evidence_without_blocking_callers(tmp_path):
    started=threading.Event();release=threading.Event()
    class Blocking(ErrorLog):
        def _write(self,record):
            started.set();release.wait(2);super()._write(record)
    log=Blocking(tmp_path/'logs',capacity=2)
    try:
        log.event('desktop.started');assert started.wait(1)
        start=time.monotonic()
        for i in range(100):log.event('desktop.event_'+str(i))
        assert time.monotonic()-start<0.3
        assert log.status()['dropped']>0
        assert log.status()['queued']<=2
    finally:release.set();log.close()


def test_unavailable_storage_and_broken_sink_do_not_escape(tmp_path):
    parent=tmp_path/'not-folder';parent.write_text('keep')
    log=ErrorLog(parent/'logs')
    assert not log.status()['available']
    emit_error(log,'broker.failed',ValueError('private'))
    log.close()
    class Broken:
        def error(self,*args,**kwargs):raise OSError('private')
    emit_error(Broken(),'broker.failed',RuntimeError('private'))


def test_export_resanitizes_records_and_refuses_existing_destination(tmp_path):
    log=ErrorLog(tmp_path/'logs')
    try:
        log.event('desktop.started');assert log.flush()
        path=tmp_path/'logs'/'error-log.jsonl'
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'schema':1,'code':'desktop.fake','level':'EVENT','timestamp':'2026-10-26T00:00:00+00:00','message':'SECRET_KEY'})+'\n')
        target=tmp_path/'support.zip';log.export(target)
        with zipfile.ZipFile(target) as z:
            assert all(b'SECRET_KEY' not in z.read(name) for name in z.namelist())
        import pytest
        with pytest.raises(FileExistsError):log.export(target)
    finally:log.close()


def test_desktop_support_export_works_disconnected_and_shutdown_drains_logger(tmp_path):
    import asyncio
    from crier.desktop_runtime import DesktopSession
    async def run():
        log=ErrorLog(tmp_path/'logs')
        session=DesktopSession(tmp_path/'desktop',start_workers=False,error_log=log)
        try:
            assert session.status()['technical_logging']['available']
            emit_error(log,'desktop.test_failure',ValueError('SECRET_KEY'))
            output=await session.support_bundle(tmp_path/'support.zip')
            assert output.endswith('support.zip')
            assert session.broker is None
        finally:await session.shutdown()
        assert not log.status()['available']
    asyncio.run(run())


def test_engine_failure_records_stack_and_preserves_existing_decision(tmp_path):
    from datetime import datetime,timedelta,timezone
    from crier.intent_engine import IntentEngine
    class Broker:
        def verify(self,environment):raise RuntimeError('SECRET_KEY')
    log=ErrorLog(tmp_path/'logs')
    try:
        engine=IntentEngine(tmp_path/'intent.sqlite3',Broker(),error_log=log)
        engine.save_settings({'enabled':True})
        now=datetime.now(timezone.utc);trade=str(uuid4())
        engine.accept(dict(version=1,event_id=str(uuid4()),trade_id=trade,sequence=1,action='enter',environment='paper',symbol='SPY',asset='stock',quantity=1,limit_price='1',created_at=now.isoformat(),expires_at=(now+timedelta(seconds=20)).isoformat()))
        assert engine.tick()[0]['state']=='reconcile_required'
        assert log.flush()
        content=(tmp_path/'logs'/'error-log.jsonl').read_text(encoding='utf-8')
        assert 'SECRET_KEY' not in content
        record=json.loads(content.splitlines()[0])
        assert record['code']=='intent.execution_failed' and record['trade_id']==trade
        assert record['stack'] and record['exception_type']=='RuntimeError'
    finally:log.close()


def test_fatal_window_failure_uses_normal_worker_shutdown(tmp_path,monkeypatch):
    import sys
    import pytest
    from crier import desktop,desktop_presence
    log=ErrorLog(tmp_path/'logs')
    closed=[]
    class Root:
        def mainloop(self):raise RuntimeError('SECRET_KEY')
    class Worker:
        error_log=log
        def __init__(self,folder):pass
        def close(self):closed.append(True);log.close()
    monkeypatch.setattr(sys,'argv',['crier-desktop'])
    monkeypatch.setattr(desktop,'data_directory',lambda:tmp_path/'desktop')
    monkeypatch.setattr(desktop.tk,'Tk',Root)
    monkeypatch.setattr(desktop,'DesktopWorker',Worker)
    monkeypatch.setattr(desktop,'DesktopApp',lambda *args,**kwargs:None)
    monkeypatch.setattr(desktop_presence,'Presence',lambda folder:None)
    with pytest.raises(RuntimeError):desktop.main()
    assert closed==[True]
    assert 'SECRET_KEY' not in (tmp_path/'logs'/'error-log.jsonl').read_text(encoding='utf-8')


def test_public_build_metadata_is_bounded_and_never_copies_unknown_fields(tmp_path):
    path=tmp_path/'build-info.json'
    public=dict(schema=1,version='0.2.0',commit='a'*40)
    path.write_text(json.dumps(public),encoding='utf-8-sig')
    assert read_build_info(path)==public
    path.write_text(json.dumps(dict(public,token='SECRET_KEY')))
    assert read_build_info(path) is None
    path.write_text('x'*3000)
    assert read_build_info(path) is None


def test_error_admission_does_not_read_source_files(tmp_path,monkeypatch):
    import linecache
    log=ErrorLog(tmp_path/'logs')
    def forbidden(*args,**kwargs):raise AssertionError('Source-file IO on diagnostic admission')
    try:
        accepted=False
        with monkeypatch.context() as patch:
            patch.setattr(linecache,'getlines',forbidden)
            patch.setattr(linecache,'checkcache',forbidden)
            patch.setattr(linecache,'lazycache',forbidden)
            try:
                try:raise RuntimeError('private')
                except RuntimeError as error:accepted=log.error('desktop.failure',error)
            except AssertionError:pass
        assert accepted
        assert log.flush()
    finally:log.close()

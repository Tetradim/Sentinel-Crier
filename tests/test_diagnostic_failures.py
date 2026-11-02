"""Optional evidence failures are observable without changing order behavior."""
import asyncio
from contextlib import contextmanager
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest

from crier.error_log import ErrorLog
from crier.intent_device import IntentDevice
from test_intent_device import Engine


class BrokenSink:
    def error(self, *args, **kwargs):
        raise OSError('PRIVATE_SECRET')


def paired(tmp_path, sink):
    device=IntentDevice(tmp_path/'device', error_log=sink)
    device.configure(dict(url='https://relay.test',token='x'*40,role='host',environment='paper'))
    device.engine=Engine()
    return device


def records(log):
    assert log.flush()
    path=log.folder/'error-log.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_dropped_trace_records_fixed_code_without_payload_or_exception_text(tmp_path,monkeypatch):
    log=ErrorLog(tmp_path/'logs')
    try:
        device=paired(tmp_path,log)
        @contextmanager
        def unavailable():
            raise sqlite3.OperationalError('PRIVATE_SECRET account=PRIVATE_ACCOUNT')
            yield
        monkeypatch.setattr(device,'db',unavailable)
        device._trace(str(uuid4()),'PRIVATE_PAYLOAD',token='PRIVATE_SECRET')
        rows=records(log)
        assert [r['code'] for r in rows]==['diagnostics.trace_dropped']
        assert 'PRIVATE_' not in json.dumps(rows)
    finally:log.close()


@pytest.mark.parametrize('broken_sink',[False,True])
def test_failed_diagnostic_queue_never_prevents_durable_host_instruction(tmp_path,broken_sink):
    log=ErrorLog(tmp_path/'logs')
    try:
        device=paired(tmp_path,BrokenSink() if broken_sink else log)
        def fail(*args):raise OSError('PRIVATE_SECRET')
        device.diagnostics.observe=fail
        event=device.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='2')
        with device.db() as db:
            assert db.execute('SELECT state FROM outgoing WHERE id=?',(event.event_id,)).fetchone()[0]=='pending'
        assert device.engine.events[-1].event_id==event.event_id
        if not broken_sink:
            rows=records(log)
            assert any(r['code']=='diagnostics.enqueue_failed' for r in rows)
            assert 'PRIVATE_SECRET' not in json.dumps(rows)
    finally:log.close()


@pytest.mark.parametrize('broken_sink',[False,True])
@pytest.mark.parametrize('attempts',[0,29])
def test_clock_and_transport_failures_keep_retry_accounting_and_stop_responsive(tmp_path,monkeypatch,broken_sink,attempts):
    log=ErrorLog(tmp_path/'logs')
    try:
        device=paired(tmp_path,BrokenSink() if broken_sink else log)
        event=device.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='2')
        with device.db() as db:
            observation=json.loads(db.execute('SELECT observation FROM diagnostic_jobs').fetchone()[0])
            db.execute("UPDATE outgoing SET state='sent'")
            observation['quote_error']='market_data_credentials_unavailable'
            db.execute('UPDATE diagnostic_jobs SET observation=?,attempts=?',(json.dumps(observation),attempts))
        original=httpx.AsyncClient
        async def run():
            stop=asyncio.Event()
            def respond(request):
                if not request.url.path.endswith('/clock'):stop.set()
                raise httpx.ConnectError('PRIVATE_SECRET',request=request)
            monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
            await asyncio.wait_for(device.diagnostics.run(stop),2)
        asyncio.run(run())
        with device.db() as db:
            job=db.execute('SELECT attempts,done,next_try FROM diagnostic_jobs WHERE event_id=?',(event.event_id,)).fetchone()
        assert job['attempts']==attempts+1 and job['done']==int(attempts==29) and job['next_try']>0
        if not broken_sink:
            rows=records(log)
            assert {r['code'] for r in rows}=={'diagnostics.clock_failed','diagnostics.transport_failed'}
            assert 'PRIVATE_SECRET' not in json.dumps(rows)
    finally:log.close()


def test_expected_wait_timeout_remains_quiet_and_stop_is_prompt(tmp_path):
    log=ErrorLog(tmp_path/'logs')
    try:
        device=IntentDevice(tmp_path/'device',error_log=log)
        async def run():
            stop=asyncio.Event()
            task=asyncio.create_task(device.diagnostics.run(stop))
            await asyncio.sleep(.3)
            stop.set()
            await asyncio.wait_for(task,1)
        asyncio.run(run())
        assert records(log)==[]
    finally:log.close()

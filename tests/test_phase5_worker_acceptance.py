"""Offline concurrent device workers; no hosted service or broker account access."""
import asyncio
from contextlib import asynccontextmanager
import json
import threading

import httpx
import pytest

from crier.intent_device import IntentDevice
from test_phase5_acceptance import AcceptanceRig, AlpacaScript, ASYNC_CLIENT, SYMBOL


class HeldHostAlpaca(AlpacaScript):
    """Accept the order at the HTTP boundary, but withhold its POST response."""

    def __init__(self):
        self.post_started = threading.Event()
        self.release_response = threading.Event()
        self.post_returned = threading.Event()
        super().__init__('synthetic-held-host')

    def respond(self, request):
        response = super().respond(request)
        if request.method == 'POST' and request.url.path == '/v2/orders':
            self.post_started.set()
            # Also bound the thread itself if cleanup regresses.
            if not self.release_response.wait(15):
                raise AssertionError('Test failed to release the held broker response')
            self.post_returned.set()
        return response


class LocalWorkerRelay(httpx.AsyncBaseTransport):
    def __init__(self, app):
        self.transport = httpx.ASGITransport(app=app)
        self.published = []
        self.delivered = []

    async def handle_async_request(self, request):
        if request.url.path.endswith('/stream'): return httpx.Response(404)
        if request.url.path.endswith('/dashboard'): return httpx.Response(404)
        if request.method == 'GET':
            # Exercise real relay long polling, with bounded shutdown latency.
            request.url = request.url.copy_set_param('wait', '0.05')
        response = await self.transport.handle_async_request(request)
        await response.aread()
        assert response.status_code == 200
        if request.method == 'POST':
            self.published.append(json.loads(request.content)['event_id'])
        else:
            self.delivered.extend(item['event']['event_id'] for item in response.json()['events'])
        return response


async def eventually(predicate, description):
    async def poll():
        while not predicate():
            await asyncio.sleep(.01)
    try:
        await asyncio.wait_for(poll(), 5)
    except TimeoutError:
        pytest.fail('Timed out waiting for ' + description)


@asynccontextmanager
async def workers(rig):
    stop = asyncio.Event()
    tasks = [asyncio.create_task(rig.host.execute_loop(stop))]
    try:
        # This establishes that publishing and receiving happen while the host's
        # real execution worker is blocked inside its synchronous HTTP adapter.
        if not rig.host_api.release_response.is_set():
            await eventually(rig.host_api.post_started.is_set, 'host broker POST')
        tasks.extend(asyncio.create_task(loop(stop)) for loop in (
            rig.host.publish_loop, rig.follower.receive_loop, rig.follower.execute_loop))
        yield
    finally:
        # Release before waiting/canceling: cancellation of to_thread cannot stop
        # the underlying broker thread and must never strand it at test teardown.
        rig.host_api.release_response.set()
        stop.set()
        for device in (rig.host, rig.follower):
            device.changed.set()
            device.publish_changed.set()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), 4)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def worker_rig(tmp_path, monkeypatch):
    rig = AcceptanceRig(tmp_path, monkeypatch)
    rig.host_api.client.close()
    rig.host_api = HeldHostAlpaca()
    rig.host = IntentDevice(tmp_path / 'host', rig.host_api.broker)
    transport = LocalWorkerRelay(rig.app)
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kwargs: ASYNC_CLIENT(transport=transport, **kwargs))
    try:
        yield rig, transport
    finally:
        rig.host_api.release_response.set()
        rig.runner.close()  # Joins the default executor before closing HTTP clients.
        rig.host_api.client.close()
        rig.follower_api.client.close()


def reconciliations(device):
    with device.engine._db() as db:
        return db.execute("SELECT count(*) FROM intent_trace WHERE stage='broker_reconciled'").fetchone()[0]


async def restart_and_replay(rig, transport, events):
    """Replay lost publish/cursor acknowledgements through restarted workers."""
    rig.host = IntentDevice(rig.folder / 'host', rig.host_api.broker)
    rig.follower = IntentDevice(rig.folder / 'follower', rig.follower_api.broker)
    assert rig.host.engine.load_settings()['enabled']
    assert rig.follower.engine.load_settings()['enabled']
    with rig.host.db() as db:
        db.execute("UPDATE outgoing SET state='pending'")
    with rig.follower.db() as db:
        db.execute('DELETE FROM cursors')
    before = reconciliations(rig.follower)
    host_before = reconciliations(rig.host)
    deliveries = len(transport.delivered)
    publishes = len(transport.published)
    async with workers(rig):
        await eventually(lambda: len(transport.published) >= publishes + 1,
                         'republished durable outbox')
        await eventually(lambda: len(transport.delivered) >= deliveries + len(events),
                         'replayed relay stream')
        await eventually(lambda: reconciliations(rig.follower) > before,
                         'restarted follower broker reconciliation')
        await eventually(lambda: reconciliations(rig.host) > host_before,
                         'restarted host broker reconciliation')
        await eventually(lambda: not rig.host.outgoing(), 'restarted publisher acknowledgement')
        # An unsent entry is superseded by its later cancellation; reconnect
        # republishes the latest intent while the receiver replays both records.
        assert transport.published[publishes:] == [events[-1].event_id]
        with rig.follower.engine._db() as db:
            assert db.execute('SELECT count(*) FROM intent_events').fetchone()[0] == len(events)
        with rig.follower.db() as db:
            assert db.execute('SELECT cursor FROM cursors').fetchone()[0] > 0
        assert len(rig.host_api.posts) == len(rig.follower_api.posts) == 1


def test_phase5_workers_submit_follower_while_host_response_held_and_replay(worker_rig):
    rig, transport = worker_rig

    async def run():
        # configure() enables hosts; a reloaded host must retain that setting.
        assert rig.host.engine.load_settings()['enabled']
        event = rig.host.command('enter', symbol=SYMBOL, asset='option',
                                 quantity=4, limit_price='0.20')
        async with workers(rig):
            await eventually(lambda: len(rig.follower_api.posts) == 1, 'follower broker POST')
            assert rig.host_api.post_started.is_set()
            assert not rig.host_api.post_returned.is_set()
            assert not rig.host_api.release_response.is_set()
            expected = dict(symbol=SYMBOL, qty='4', side='buy', type='limit',
                            client_order_id='si-' + event.event_id + '-b', limit_price='0.20',
                            time_in_force='day', position_intent='buy_to_open')
            assert rig.host_api.posts == rig.follower_api.posts == [expected]
            assert all(row['filled_qty'] == '0' for row in rig.host_api.orders.values())
        await restart_and_replay(rig, transport, [event])

    rig.runner.run(run())


def test_phase5_workers_cancel_propagates_while_host_response_held_and_restarts(worker_rig):
    rig, transport = worker_rig

    async def run():
        entry = rig.host.command('enter', symbol=SYMBOL, asset='option',
                                 quantity=4, limit_price='0.20')
        async with workers(rig):
            await eventually(lambda: len(rig.follower_api.posts) == 1, 'follower broker POST')
            cancellation = rig.host.command('cancel', trade_id=entry.trade_id)
            await eventually(lambda: len(rig.follower_api.cancels) == 1,
                             'follower broker cancellation before host response')
            assert not rig.host_api.post_returned.is_set()
            assert not rig.host_api.release_response.is_set()
            assert rig.host_api.cancels == []
            assert cancellation.event_id in transport.delivered
            assert rig.follower.engine.status()['trades'][0]['invalid']
            # Free the host only after observing remote cancellation. Wake its
            # worker to reconcile the accepted order against the latest intent.
            rig.host_api.release_response.set()
            rig.host.changed.set()
            await eventually(lambda: len(rig.host_api.cancels) == 1, 'host broker cancellation')
        await restart_and_replay(rig, transport, [entry, cancellation])
        for device in (rig.host, rig.follower):
            assert device.engine.status()['trades'][0]['invalid']
            assert device.engine.status()['orders'][0]['status'] == 'canceled'
        assert len(rig.host_api.cancels) == len(rig.follower_api.cancels) == 1

    rig.runner.run(run())

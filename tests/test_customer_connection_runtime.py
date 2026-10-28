import asyncio
import threading
from crier.desktop_runtime import DesktopSession
from crier import customer_readiness


def test_connection_test_refuses_disconnected_without_broker_calls(tmp_path):
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        result=await session.connection_test()
        assert result['ready'] is False
        assert result['rows'][0]['code']=='connect_first'
        await session.shutdown()
    asyncio.run(run())


def test_canceled_probe_drains_read_before_broker_can_close(tmp_path, monkeypatch):
    monkeypatch.setattr(customer_readiness, "_bounded_account",
        lambda broker, env, account, cancelled, **kwargs: broker.verify(env))
    entered=threading.Event();release=threading.Event();events=[]
    class Broker:
        environment='paper'
        def verify(self,environment):
            events.append('read');entered.set();release.wait(5);events.append('read_done');return 'account-a'
        def close(self):events.append('closed')
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        session.broker=Broker();session.environment='paper';session.account='account-a';session.mode='alerts'
        session.stop=asyncio.Event()
        probe=asyncio.create_task(session.connection_test())
        assert await asyncio.to_thread(entered.wait,3)
        probe.cancel();closing=asyncio.create_task(session.disconnect())
        await asyncio.sleep(.01)
        assert not closing.done() and 'closed' not in events
        release.set()
        await asyncio.gather(probe,return_exceptions=True);await closing
        assert events==['read','read_done','closed']
        await session.shutdown()
    try:asyncio.run(run())
    finally:release.set()


def test_connected_probe_returns_time_and_environment_without_enabling_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(customer_readiness, "_bounded_account",
        lambda broker, env, account, cancelled, **kwargs: broker.verify(env))
    events=[]
    class Broker:
        environment='paper'
        def verify(self,environment):events.append(('verify',environment));return 'account-a'
        def close(self):events.append(('close',))
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        session.broker=Broker();session.environment='paper';session.account='account-a';session.mode='alerts'
        session.stop=asyncio.Event()
        result=await session.connection_test()
        assert result['ready'] and result['environment']=='paper' and result['checked_at']
        assert result['delivery']=='not_tested'
        assert events==[('verify','paper')]
        await session.shutdown()
    asyncio.run(run())

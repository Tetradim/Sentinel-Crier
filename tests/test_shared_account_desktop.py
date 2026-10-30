import asyncio
import json
import pytest
from crier.desktop_connections import DesktopConnections
from crier.desktop_runtime import DesktopSession
from crier.managed_account import ManagedAccount
from crier.allocation_bank import BankConflict
from test_managed_account import Broker
from test_allocation_bank import SCOPE, SYMBOL
from test_desktop_connections import PAIR
from test_intent_engine import event


def manager_at(path):
    broker=Broker()
    broker.close=lambda:None
    broker.position=lambda symbol:broker.positions.get(symbol,0)
    async def account(*args,**kwargs): return SCOPE.account
    async def poll(): return None
    def factory(folder,**kwargs):
        session=DesktopSession(folder,account_lookup=account,broker_factory=lambda *a,**k:broker,start_workers=False,**kwargs)
        session.poll_alerts=poll
        return session
    return DesktopConnections(path,factory),broker


def test_explicit_bank_setup_admits_two_routes_and_survives_restart(tmp_path):
    async def run():
        manager,broker=manager_at(tmp_path)
        alice=manager.selected
        await manager.invoke(alice,'connect',json.dumps(PAIR),'fake-key','fake-secret')
        state=await manager.invoke(alice,'bank_enable')
        assert state['enabled'] and not manager.sessions[alice].broker
        await manager.invoke(alice,'bank_configure','option','units','3','0')
        dave=manager.add('Dave')
        other_pair=dict(PAIR,token='d'*40)
        for route,pair in ((alice,PAIR),(dave,other_pair)):
            await manager.invoke(route,'connect',json.dumps(pair),'fake-key','fake-secret')
            assert isinstance(manager.sessions[route].broker,ManagedAccount)
        await manager.invoke(dave,'bank_configure','option','equity_percent','5','0')
        for route,qty in ((alice,3),(dave,5)):
            engine=manager.sessions[route].device.engine
            engine.save_settings({'enabled':True})
            instruction=event(symbol=SYMBOL,asset='option',quantity=qty,limit_price='0.20')
            engine.accept(instruction)
            result=engine.tick()
            assert result and result[0]['state']=='submitted',result
        assert broker.posts==2
        assert len(manager.bank.active(SCOPE))==2
        await manager.invoke(alice,'disconnect_all')
        restarted,_=manager_at(tmp_path)
        assert len(restarted.bank.active(SCOPE))==2
        assert restarted.bank.account(SCOPE)['available']=='840'
        assert all(session.broker is None for session in restarted.sessions.values())
    asyncio.run(run())


def test_setup_cannot_abandon_old_working_order(tmp_path):
    async def run():
        manager,broker=manager_at(tmp_path);route=manager.selected
        await manager.invoke(route,'connect',json.dumps(PAIR),'fake-key','fake-secret')
        engine=manager.sessions[route].device.engine
        engine.save_settings({'enabled':True})
        instruction=event(symbol=SYMBOL,asset='option',quantity=3,limit_price='0.20')
        engine.accept(instruction);engine.tick()
        assert broker.posts==1
        with pytest.raises(BankConflict): await manager.invoke(route,'bank_enable')
        assert not manager.bank.enabled(SCOPE)
        assert broker.posts==1
        assert not manager.sessions[route].broker
    asyncio.run(run())

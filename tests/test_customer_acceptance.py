"""Fresh-customer flows through actual controllers with intercepted HTTP only."""
import asyncio
from decimal import Decimal
import json
import httpx
import pytest
from crier.desktop_runtime import DesktopSession
from test_alpaca import activity

WEBHOOK='https://discord.com/api/webhooks/123/customer-fixture-token'
CONTRACT='SPY261218C00750000'


def intercepted(monkeypatch):
    from crier import desktop_runtime as runtime
    state=dict(fills=[],posts=[],requests=[],uncertain=False)
    def handle(request):
        state['requests'].append((request.method,request.url.host,request.url.path))
        if request.url.host in ('paper-api.alpaca.markets','api.alpaca.markets'):
            assert request.method=='GET', 'Alerts must never place brokerage orders'
            if request.url.path=='/v2/account': return httpx.Response(200,json={'id':'fixture-account','trading_blocked':True})
            assert request.url.path=='/v2/account/activities/FILL'
            return httpx.Response(200,json=list(state['fills']))
        assert request.url.host=='discord.com' and request.method=='POST' and request.url.path.startswith('/api/webhooks/')
        state['posts'].append(json.loads(request.content))
        if state['uncertain']: raise httpx.ReadTimeout('Injected acknowledgement loss',request=request)
        return httpx.Response(200,json={'id':str(1000+len(state['posts']))})
    sync,async_client=httpx.Client,httpx.AsyncClient
    monkeypatch.setattr(runtime.httpx,'Client',lambda **kw:sync(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(runtime.httpx,'AsyncClient',lambda **kw:async_client(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(runtime,'IntentDevice',lambda *a,**kw:pytest.fail('Alerts journey must not create an order engine'))
    return state


def test_customer_alerts_first_receipt_exact_option_values_and_reconnect(tmp_path,monkeypatch):
    state=intercepted(monkeypatch)
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        try:
            connected=await session.connect_alerts('paper','fixture-key','fixture-secret')
            assert connected['alerts']['state']=='observing' and session.device is None
            await session.discord_configure(WEBHOOK,False)
            await session.discord_settings({'format':'homebrew'})
            assert session.discord_preview() and not state['posts']
            test=await session.discord_test()
            assert test['status']=='sent' and test['fill']['verification']=='synthetic'
            assert not session.discord_status()['enabled'] and len(state['posts'])==1
            state['fills'].append(activity(id='buy-paper',order_id='buy-order',symbol=CONTRACT,qty='2',cum_qty='2',price='0.20'))
            await session.poll_alerts()
            with httpx.Client() as client: assert not session.deliver_alerts(client)
            assert len(state['posts'])==1
            await session.discord_configure('',True)
            with httpx.Client() as client: session.deliver_alerts(client)
            state['fills'].append(activity(id='sell-paper',order_id='sell-order',symbol=CONTRACT,side='sell',qty='1',cum_qty='1',price='0.22',transaction_time='2026-10-19T14:31:00Z'))
            await session.poll_alerts()
            with httpx.Client() as client: session.deliver_alerts(client)
            rows=[r for r in session.publisher.store.history() if not r['id'].startswith('test-')]
            assert len(rows)==2 and all(r['status']=='sent' and r['message_id'] for r in rows)
            fills={r['fill']['side'].lower():r['fill'] for r in rows}
            assert set(fills)=={'buy','sell'}
            for fill in fills.values():
                assert fill['symbol']==CONTRACT and fill['contract']=='SPY $750C'
                assert fill['expiration']=='2026-12-18'
            assert Decimal(fills['buy']['quantity'])==2 and Decimal(fills['buy']['price'])==Decimal('0.20')
            assert Decimal(fills['sell']['quantity'])==1 and Decimal(fills['sell']['price'])==Decimal('0.22')
            assert len(state['posts'])==3 and 'SPY' in json.dumps(state['posts'][1:])
        finally: await session.disconnect()
        restarted=DesktopSession(tmp_path,start_workers=False)
        try:
            await restarted.connect_alerts('paper','','')
            assert not restarted.discord_status()['enabled'] and restarted.device is None
            with httpx.Client() as client: assert not restarted.deliver_alerts(client)
            await restarted.discord_configure('',True)
            with httpx.Client() as client: assert not restarted.deliver_alerts(client)
            assert len(state['posts'])==3 and len(restarted.publisher.store.history())==3
        finally: await restarted.disconnect()
        assert not (tmp_path/'journal').exists()
    asyncio.run(run())


def test_customer_uncertain_receipt_survives_reconnect_without_resend(tmp_path,monkeypatch):
    state=intercepted(monkeypatch)
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        try:
            await session.connect_alerts('paper','fixture-key','fixture-secret')
            await session.discord_configure(WEBHOOK,True)
            state['fills'].append(activity(symbol=CONTRACT,qty='3',cum_qty='3',price='0.20'))
            await session.poll_alerts(); state['uncertain']=True
            with httpx.Client() as client: session.deliver_alerts(client)
            row=session.publisher.store.history()[0]
            assert row['status']=='uncertain' and len(state['posts'])==1
            identity=row['id']; evidence=row['fill']
        finally: await session.disconnect()
        restarted=DesktopSession(tmp_path,start_workers=False)
        try:
            await restarted.connect_alerts('paper','',''); await restarted.discord_configure('',True)
            with httpx.Client() as client: assert not restarted.deliver_alerts(client)
            with pytest.raises(ValueError): restarted.discord_retry(identity)
            closed=restarted.discord_close(identity)
            assert closed['fill']==evidence and closed['status']=='closed' and 'uncertain' in closed['note']
            assert len(state['posts'])==1
        finally: await restarted.disconnect()
    asyncio.run(run())


def test_customer_live_read_consent_does_not_require_completing_paper_practice(tmp_path,monkeypatch):
    state=intercepted(monkeypatch)
    async def run():
        session=DesktopSession(tmp_path,start_workers=False)
        try:
            with pytest.raises(ValueError): await session.connect_alerts('live','fixture-key','fixture-secret')
            assert not state['requests']
            result=await session.connect_alerts('live','fixture-key','fixture-secret',allow_live=True)
            assert result['connected'] and result['environment']=='live'
            assert not session.discord_status()['enabled'] and not state['posts']
            assert all(host=='api.alpaca.markets' and method=='GET' for method,host,_ in state['requests'])
        finally: await session.disconnect()
    asyncio.run(run())

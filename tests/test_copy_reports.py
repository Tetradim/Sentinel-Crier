import json
from crier.intent_device import IntentDevice
from crier.copy_dashboard import StatusReport
from test_intent_engine import Broker, event


def test_reports_use_cumulative_prices_without_changing_execution(tmp_path):
    broker=Broker(); d=IntentDevice(tmp_path,broker)
    d.configure(dict(url='https://example.test',token='x'*40,environment='paper',role='host'))
    e=event(quantity=2); d.engine.accept(e); d.engine.tick()
    cid=broker.sent[0]['client_order_id']
    broker.orders[cid].update(status='filled',filled_qty='2',filled_avg_price='0.20')
    d.engine.tick(); before=len(broker.sent)
    report=d.reporter.collect()[0]
    assert report['bought']==2 and report['buy_premium']=='0.40'
    assert report['currency'] is None and report['fees'] is None
    d.reporter.queue(d.fingerprint,'status:'+e['event_id'],report)
    d.reporter.queue(d.fingerprint,'status:'+e['event_id'],report)
    with d.db() as db:
        row=db.execute('SELECT payload FROM copy_outbox').fetchone()
        assert StatusReport.model_validate_json(row[0]).revision==1
    restarted=IntentDevice(tmp_path,broker)
    with restarted.db() as db: assert db.execute('SELECT pending FROM copy_outbox').fetchone()[0]==1
    assert len(broker.sent)==before

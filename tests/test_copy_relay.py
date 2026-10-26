from hashlib import sha256
from uuid import uuid4
import pytest
from crier.intent_relay import IntentRelay
from crier.copy_relay import save, snapshot
from crier.copy_dashboard import StatusReport, PresenceReport
from test_intent_relay import event


def receiver(relay,pair,start=0):
    token=str(uuid4()); actor=str(uuid4())
    with relay.db() as db:
        db.execute('INSERT INTO receivers VALUES (?,?,?,?,?,?)',(actor,pair['id'],sha256(token.encode()).hexdigest(),1,0,start))
    return token,actor


def test_dashboard_scope_revision_and_restart(tmp_path):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Host','paper')
    a,actor=receiver(relay,pair); b,other=receiver(relay,pair)
    e=event(); relay.publish(pair['host_token'],e)
    report=StatusReport(event_id=e.event_id,revision=1,observed_at=e.created_at.isoformat(),state='filled',bought=2,sold=0,buy_premium='.40'.replace('.40','0.40'))
    save(relay,a,report); save(relay,b,report)
    assert {s['actor'] for s in snapshot(relay,pair['host_token'])['statuses']}=={actor,other}
    assert [s['actor'] for s in snapshot(relay,a)['statuses']]==[actor]
    assert save(relay,a,report)=={'stored':True}
    with pytest.raises(ValueError): save(relay,a,report.model_copy(update={'state':'working'}))
    with pytest.raises(ValueError): save(relay,a,report.model_copy(update={'revision':2,'bought':1}))
    assert len(snapshot(IntentRelay(relay.path),a)['statuses'])==1
    with relay.db() as db: db.execute('UPDATE receivers SET revoked=1 WHERE id=?',(actor,))
    with pytest.raises(PermissionError): snapshot(relay,a)
    host=snapshot(relay,pair['host_token'])
    assert next(m for m in host['members'] if m['actor']==actor)['revoked']


def test_enrollment_and_metadata_binding(tmp_path):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Host','paper')
    e=event(); cursor=relay.publish(pair['host_token'],e)['cursor']
    token,_=receiver(relay,pair,cursor)
    report=StatusReport(event_id=e.event_id,revision=1,observed_at=e.created_at.isoformat(),state='received',bought=0,sold=0)
    with pytest.raises(LookupError): save(relay,token,report)
    assert snapshot(relay,token)['events']==[]
    with pytest.raises(ValueError): save(relay,pair['host_token'],report.model_copy(update={'currency':'USD','multiplier':1}))
    presence=PresenceReport(revision=1,observed_at=e.created_at.isoformat(),platform='windows',transport='push',entries_enabled=False)
    save(relay,token,presence,presence=True)
    assert snapshot(relay,token)['members'][1]['presence']['transport']=='push'

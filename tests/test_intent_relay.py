from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from crier.intent_protocol import IntentEvent
from crier.intent_relay import IntentRelay

def event(**changes):
    now = datetime.now(timezone.utc)
    return IntentEvent(**(dict(version=1,event_id=str(uuid4()),trade_id=str(uuid4()),sequence=1,action='enter',environment='paper',symbol='SPY261212C00750000',asset='option',quantity=2,limit_price='0.20',created_at=now,expires_at=now+timedelta(seconds=10)) | changes))

def test_relay_scope_replay_and_revocation(tmp_path):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Trader','paper'); e=event()
    first=relay.publish(pair['host_token'],e)
    assert relay.publish(pair['host_token'],e)==first
    assert relay.read(pair['follower_token'],0)['events'][0]['event']==e.to_dict()
    assert relay.read(pair['follower_token'],first['cursor'])['events']==[]
    with pytest.raises(PermissionError): relay.publish(pair['follower_token'],e)
    with pytest.raises(PermissionError): relay.read(pair['host_token'],0)
    relay.revoke(pair['id'])
    with pytest.raises(PermissionError): relay.read(pair['follower_token'],0)

def test_sequence_cannot_change_contents_and_identity_pinned(tmp_path):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Trader','paper'); e=event()
    relay.publish(pair['host_token'],e)
    with pytest.raises(ValueError): relay.publish(pair['host_token'],e.model_copy(update={'quantity':3}))
    with pytest.raises(ValueError): relay.publish(pair['host_token'],event(trade_id=e.trade_id,sequence=1))
    with pytest.raises(ValueError): relay.publish(pair['host_token'],event(trade_id=e.trade_id,sequence=2,symbol='AAPL',asset='stock'))
    with pytest.raises(ValueError): relay.publish(pair['host_token'],event(environment='live'))

def test_cancel_before_enter_remains_in_stream(tmp_path):
    relay=IntentRelay(tmp_path/'relay.db'); pair=relay.create('Trader','paper'); e=event()
    cancel=event(trade_id=e.trade_id,sequence=2,action='cancel')
    relay.publish(pair['host_token'],cancel); relay.publish(pair['host_token'],e)
    rows=relay.read(pair['follower_token'],0)['events']
    assert [r['event']['action'] for r in rows]==['cancel','enter']
    assert IntentRelay(tmp_path/'relay.db').read(pair['follower_token'],0)==relay.read(pair['follower_token'],0)

@pytest.mark.parametrize('changes',[dict(quantity=1.2),dict(limit_price='NaN'),dict(event_id='bad'),dict(symbol='SPY261399C00750000'),dict(asset='stock'),dict(expires_at=datetime.now(timezone.utc)+timedelta(minutes=2))])
def test_invalid_wire_event(changes):
    with pytest.raises(ValueError): event(**changes)

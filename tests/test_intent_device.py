from datetime import datetime,timezone
from uuid import uuid4
import pytest
from crier.intent_device import IntentDevice
from test_intent_relay import event

class Engine:
    def __init__(self): self.events=[]; self.settings={'enabled':True}
    def load_settings(self): return self.settings
    def accept(self,e): self.events.append(e)
    def status(self): return {'orders':[],'trades':[],'settings':self.settings}
    def save_settings(self,value): self.settings.update(value); return self.settings

def device(tmp_path):
    result=IntentDevice(tmp_path)
    result.configure({'url':'https://example.test','token':'x'*40,'environment':'paper','role':'host'})
    result.engine=Engine()
    return result

def test_host_journals_before_dispatch_and_sequences(tmp_path):
    d=device(tmp_path)
    first=d.command('enter',symbol='SPY261212C00750000',asset='option',quantity=2,limit_price='0.20')
    second=d.command('cancel',trade_id=first.trade_id)
    assert first.sequence==1 and second.sequence==2
    assert d.engine.events==[first,second]
    assert d.outgoing()[0]['action']=='cancel' # obsolete entry invalidated before sending
    assert 'token' not in d.status()['pair']

def test_host_command_wakes_idle_publisher(tmp_path):
    d=device(tmp_path)
    assert not d.publish_changed.is_set()
    d.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='1')
    assert d.publish_changed.is_set()

def test_receiver_cannot_publish(tmp_path):
    d=IntentDevice(tmp_path)
    d.configure({'url':'https://example.test','token':'x'*40,'environment':'paper','role':'follower'})
    d.engine=Engine()
    with pytest.raises(ValueError): d.command('enter',symbol='AAPL',asset='stock',quantity=1,limit_price='1')

def test_pairing_secret_is_not_plaintext(tmp_path):
    d=device(tmp_path)
    assert b'x'*40 not in (tmp_path/'intent-pairing.secret').read_bytes()
    reloaded=IntentDevice(tmp_path)
    assert reloaded.pair['token']=='x'*40

@pytest.mark.parametrize('url',['http://example.com','https://user:pass@example.com','https://example.com/path','https://example.com?token=x'])
def test_invalid_pairing_url(tmp_path,url):
    with pytest.raises(ValueError): IntentDevice(tmp_path).configure({'url':url,'token':'x'*40,'environment':'paper','role':'host'})


def test_replace_cannot_poison_outbox_with_changed_symbol(tmp_path):
    d=device(tmp_path)
    first=d.command('enter',symbol='AAPL',asset='stock',quantity=2,limit_price='1')
    with pytest.raises(ValueError): d.command('replace',trade_id=first.trade_id,symbol='MSFT')
    assert len(d.outgoing())==1
    cancel=d.command('cancel',trade_id=first.trade_id)
    assert cancel.sequence==2

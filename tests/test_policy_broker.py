import httpx
import pytest
from crier.intent_broker import AlpacaIntentBroker, BrokerNotSubmitted, BrokerSuperseded


def adapter(changes=None):
    posts=[]; changes=changes or {}
    def respond(request):
        if request.method=='POST':
            posts.append(__import__('json').loads(request.content)); return httpx.Response(200,json={})
        if request.url.path=='/v2/account':
            body=dict(id='account',status='ACTIVE',currency='USD')
        else:
            body=dict(symbol='SPY261218C00750000',tradable=True,status='active',size='100')
        body.update(changes.get(request.url.path,{}))
        return httpx.Response(200,json=body)
    broker=AlpacaIntentBroker('paper','test','test','account',httpx.Client(transport=httpx.MockTransport(respond)))
    return broker,posts


def order():
    return dict(symbol='SPY261218C00750000',asset='option',side='buy',qty='5',type='limit',limit_price='0.20',client_order_id='cid')


def test_fresh_metadata_and_internal_binding_never_reach_broker_body():
    broker,posts=adapter(); request=order()
    request['_policy_metadata']=broker.metadata(dict(request,environment='paper'))
    broker.submit_checked(request,lambda:True)
    assert len(posts)==1
    assert '_policy_metadata' not in posts[0] and 'asset' not in posts[0]
    assert posts[0]['qty']=='5' and posts[0]['limit_price']=='0.20'


@pytest.mark.parametrize('change',[{'currency':'EUR'},{'currency':None}])
def test_changed_account_currency_cannot_post(change):
    broker,posts=adapter({'/v2/account':change}); request=order()
    request['_policy_metadata']=dict(account='account',environment='paper',symbol=request['symbol'],asset='option',currency='USD',multiplier=100)
    with pytest.raises(BrokerNotSubmitted): broker.submit_checked(request,lambda:True)
    assert not posts


def test_changed_binding_and_final_pause_cannot_post():
    broker,posts=adapter(); request=order()
    request['_policy_metadata']=dict(broker.metadata(dict(request,environment='paper')),account='other')
    with pytest.raises(BrokerSuperseded): broker.submit_checked(request,lambda:True)
    request['_policy_metadata']['account']='account'
    with pytest.raises(BrokerSuperseded): broker.submit_checked(request,lambda:False)
    assert not posts

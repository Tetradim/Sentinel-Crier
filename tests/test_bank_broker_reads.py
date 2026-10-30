import httpx
import pytest
from crier.intent_broker import AlpacaIntentBroker


def broker(positions):
    def respond(request):
        assert request.method=='GET'
        body=(dict(id='account',status='ACTIVE',currency='USD',cash='1000',equity='2000',
                   non_marginable_buying_power='800',options_buying_power='600')
              if request.url.path=='/v2/account' else positions)
        return httpx.Response(200,json=body)
    return AlpacaIntentBroker('paper','fake','fake','account',httpx.Client(transport=httpx.MockTransport(respond)))


def test_funds_use_available_cash_without_margin_or_duplicate_order_credit():
    raw=broker([])
    try:
        funds=raw.allocation_funds()
        assert funds['cash']=='600' and funds['equity']=='2000'
        assert funds['observed_at'].utcoffset() is not None
    finally:raw.close()


@pytest.mark.parametrize('position',[
    dict(symbol='SPY',qty='1.5',side='long',asset_class='us_equity'),
    dict(symbol='SPY',qty='1',side='short',asset_class='us_equity'),
    dict(symbol='SPY',qty='NaN',side='long',asset_class='us_equity'),
])
def test_unsupported_inventory_cannot_be_adopted(position):
    raw=broker([position])
    try:
        with pytest.raises(ValueError):raw.allocation_positions()
    finally:raw.close()

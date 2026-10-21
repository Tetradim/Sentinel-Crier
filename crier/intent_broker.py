"""Alpaca order adapter with explicit environment and account identity pinning.

No HTTP retries are configured: a timed-out POST is resolved by the engine using
its persisted client_order_id. Credentials are kept in memory, never the journal.
"""
from decimal import Decimal
from urllib.parse import quote
import httpx

HOSTS={'paper':'https://paper-api.alpaca.markets','live':'https://api.alpaca.markets'}

class BrokerNotSubmitted(RuntimeError):
    """Broker definitely did not accept an order; safe to invalidate the intent."""

class BrokerSuperseded(RuntimeError):
    """Preflight finished but the durable instruction changed before dispatch."""

class AlpacaIntentBroker:
    def __init__(self, environment, key, secret, account, client=None):
        if environment not in HOSTS or not all(isinstance(x,str) and x.strip() for x in (key,secret,account)):
            raise ValueError('Environment, credentials and pinned account are required')
        self.environment, self.account = environment, account
        self.url=HOSTS[environment]
        self.client=client or httpx.Client(headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret},timeout=15,trust_env=False,follow_redirects=False)
    def _request(self, method, path, **kwargs):
        response=self.client.request(method,self.url+path,follow_redirects=False,**kwargs)
        response.raise_for_status()
        return response.json() if response.content else None
    def verify(self, environment):
        if environment!=self.environment: raise ValueError('Broker environment mismatch')
        account=self._request('GET','/v2/account')
        if account.get('id')!=self.account: raise ValueError('Broker account mismatch')
        if account.get('status')!='ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'): raise ValueError('Account cannot trade')
        return self.account
    def _asset(self, symbol, asset):
        if asset=='option':
            contract=self._request('GET','/v2/options/contracts/'+quote(symbol,safe=''))
            if contract.get('symbol')!=symbol or not contract.get('tradable') or contract.get('status')!='active' or Decimal(str(contract.get('size','0')))!=100: raise ValueError('Unsupported option contract')
        else:
            info=self._request('GET','/v2/assets/'+quote(symbol,safe=''))
            if info.get('symbol')!=symbol or info.get('class')!='us_equity' or not info.get('tradable') or info.get('status')!='active': raise ValueError('Asset is not tradable')
    def submit(self, order):
        return self.submit_checked(order, lambda: True)
    def submit_checked(self, order, can_submit):
        try:
            self.verify(self.environment)
            self._asset(order['symbol'],order['asset'])
        except Exception as exc:
            raise BrokerNotSubmitted('Account or instrument preflight failed') from exc
        body={k:v for k,v in order.items() if k!='asset'}
        body['time_in_force']='day'
        # position_intent also makes Alpaca reject a close that could create a short.
        body['position_intent']='buy_to_open' if order['side']=='buy' else 'sell_to_close'
        if not can_submit(): raise BrokerSuperseded('Intent superseded during preflight')
        try: return self._request('POST','/v2/orders',json=body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400,401,403,404):
                raise BrokerNotSubmitted('Broker rejected submission') from exc
            if exc.response.status_code==422:
                # A duplicate client_order_id may mean an earlier POST succeeded.
                # Only explicitly identified validation failures are definitive.
                try:
                    detail=exc.response.json()
                except ValueError:
                    detail={}
                message=str(detail.get('message','')).lower() if isinstance(detail,dict) else ''
                duplicate=any(word in message for word in ('client_order_id','duplicate','already exists','must be unique'))
                validation=any(word in message for word in ('invalid qty','invalid quantity','quantity must','invalid limit_price','invalid limit price','price must'))
                if validation and not duplicate:
                    raise BrokerNotSubmitted('Broker rejected order parameters') from exc
            raise
    def lookup(self, client_order_id):
        try: return self._request('GET','/v2/orders:by_client_order_id',params={'client_order_id':client_order_id})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==404: return None
            raise
    def cancel(self, broker_order_id):
        self.verify(self.environment)
        try: return self._request('DELETE','/v2/orders/'+quote(broker_order_id,safe=''))
        except httpx.HTTPStatusError as exc:
            # A fill can race cancellation; the engine obtains terminal truth next tick.
            if exc.response.status_code in (404,422): return None
            raise
    def position(self, symbol):
        try: row=self._request('GET','/v2/positions/'+quote(symbol,safe=''))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==404: return Decimal(0)
            raise
        if row.get('symbol')!=symbol: raise ValueError('Position identity mismatch')
        if 'qty_available' not in row: raise ValueError('Available position quantity missing')
        quantity=Decimal(str(row['qty_available']))
        if not quantity.is_finite(): raise ValueError('Invalid position quantity')
        return max(Decimal(0),quantity)
    def close(self): self.client.close()

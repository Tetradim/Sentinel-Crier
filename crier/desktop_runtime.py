"""Desktop lifecycle. All methods run on one background asyncio loop."""
import asyncio
from concurrent.futures import Future
import json
import hashlib
import os
from pathlib import Path
import threading
from .service_url import service_url

import httpx

from .device_secrets import load_secret, save_secret
from .intent_broker import AlpacaIntentBroker, HOSTS
from .intent_device import IntentDevice
from .intent_routes import Pair
from .connection_client import ConnectionClient
from .store import Store
from .discord_settings import DiscordPublisher


def data_directory():
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()/'.local/share'))) / 'SentinelCrier' / 'Desktop'


async def discover_account(environment, key, secret, client=None):
    if environment not in HOSTS or not key.strip() or not secret.strip():
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers={
            'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}, follow_redirects=False)
        response.raise_for_status()
        row = response.json()
        if not row.get('id') or row.get('status') != 'ACTIVE' or row.get('account_blocked') or row.get('trading_blocked'):
            raise ValueError('The selected Alpaca account is unavailable for trading.')
        return row['id']
    except (httpx.HTTPError, json.JSONDecodeError):
        raise ValueError('Cannot verify Alpaca account. Check credentials, environment and connection.') from None
    finally:
        if owned:
            await client.aclose()


async def discover_alerts_account(environment, key, secret, client=None):
    """Verify read access; trading permission is irrelevant for fill monitoring."""
    from .alpaca import _identity
    if environment not in HOSTS or not key.strip() or not secret.strip():
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers={
            'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}, follow_redirects=False)
        response.raise_for_status()
        return _identity(response.json().get('id'))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ValueError('Cannot verify Alpaca read access. Check credentials, environment and connection.') from None
    finally:
        if owned:
            await client.aclose()


class AlpacaFillReader:
    """Read-only account adapter: deliberately has no order mutation methods."""
    def __init__(self, environment, key, secret, account):
        self.environment, self.account = environment, account
        self.client = httpx.Client(headers={'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret},
                                   timeout=15, trust_env=False, follow_redirects=False)

    def verify(self, environment):
        if environment != self.environment:
            raise ValueError('Broker environment mismatch')
        response = self.client.get(HOSTS[environment]+'/v2/account', follow_redirects=False)
        response.raise_for_status()
        if response.json().get('id') != self.account:
            raise ValueError('Broker account mismatch')
        return self.account

    def close(self):
        self.client.close()


class DesktopSession:
    def __init__(self, folder, account_lookup=discover_account,
                 broker_factory=AlpacaIntentBroker, start_workers=True,
                 alerts_lookup=discover_alerts_account, alerts_factory=AlpacaFillReader):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.credentials = self.folder/'desktop-credentials.secret'
        self.alerts_credentials = self.folder/'desktop-alerts-credentials.secret'
        self.alerts_lookup, self.alerts_factory = alerts_lookup, alerts_factory
        self.environment = ''
        self.mode = 'disconnected'
        self.alert_poll = asyncio.Lock()
        self.account_lookup = account_lookup
        self.broker_factory = broker_factory
        self.start_workers = start_workers
        self.broker = None
        self.device = None
        self.tasks = []
        self.stop = None
        self.account = ''
        self.closing = False
        self.lifecycle = asyncio.Lock()
        self.intent_publisher=DiscordPublisher(self.folder,Store(self.folder/"alerts.sqlite3"))
        self.publisher = self.intent_publisher
        self.publisher.store.recover()
        self.alert_state={'state':'stopped'}

    def connection_client(self):
        saved=json.loads(load_secret(self.credentials)) if self.credentials.exists() else {}
        return ConnectionClient(self.folder/'connection-pair.secret', existing=saved.get('pair'))

    async def host(self, origin, environment):
        async with self.lifecycle:
            self.require_disconnected()
            return await self.connection_client().host(origin,environment)

    async def receive(self, invitation, origin):
        async with self.lifecycle:
            self.require_disconnected()
            return await self.connection_client().receive(invitation,origin)

    async def receivers(self):
        if self.mode == 'alerts': raise ValueError('Connect a host pairing to manage receivers.')
        return await self.connection_client().receivers()

    async def revoke_receiver(self, identity):
        if self.mode == 'alerts': raise ValueError('Connect a host pairing to manage receivers.')
        return await self.connection_client().revoke_receiver(identity)

    def discord_status(self):
        return self.publisher.status()

    def discord_configure(self, webhook, enabled):
        return self.publisher.configure(webhook, enabled, allow_initial=self.mode == 'alerts')

    def discord_settings(self, settings):
        return self.publisher.settings(settings)

    def discord_preview(self, scenario='option_buy', settings=None):
        return self.publisher.preview(scenario,settings)

    async def discord_test(self):
        def send():
            with httpx.Client(trust_env=False,follow_redirects=False) as client:
                return self.publisher.test_message(client)
        return await asyncio.to_thread(send)

    async def poll_alerts(self):
        from .alpaca import poll_once
        async with self.alert_poll:
            if not self.broker or not hasattr(self.broker,'client'): return
            broker, account = self.broker, self.account
            def poll():
                broker.verify(broker.environment)
                return poll_once(self.publisher.store,broker.client,account,broker.environment)
            try:
                self.alert_state=await asyncio.to_thread(poll)
            except Exception:
                self.alert_state={'state':'reconnecting','message':'Fill activity unavailable; saved cursor retained. No inferred fills published.'}

    def require_disconnected(self):
        if self.broker or self.device or self.closing:
            raise ValueError('Disconnect before changing connection settings.')

    async def connect_alerts(self, environment, key, secret, allow_live=False):
        async with self.lifecycle:
            self.require_disconnected()
            if environment not in HOSTS:
                raise ValueError('Select paper or live environment.')
            if environment == 'live' and not allow_live:
                raise ValueError('Select Allow live read access to connect a live account.')
            saved = json.loads(load_secret(self.alerts_credentials)) if self.alerts_credentials.exists() else {}
            if bool(key.strip()) != bool(secret.strip()):
                raise ValueError('Enter both credentials, or leave both blank to reuse saved credentials.')
            if saved and saved['environment'] != environment:
                raise ValueError('Saved alerts credentials are pinned to their original environment.')
            key, secret = (key.strip(), secret.strip()) if key.strip() else (saved.get('key',''), saved.get('secret',''))
            account = await self.alerts_lookup(environment, key, secret)
            if saved and saved['account'] != account:
                raise ValueError('Alerts monitoring is pinned to its original account.')
            broker = self.alerts_factory(environment, key, secret, account)
            previous_publisher = self.publisher
            enrollment = None
            try:
                scope = hashlib.sha256(json.dumps([environment, account]).encode()).hexdigest()
                profile = self.folder/'alerts-profiles'/scope
                profile.mkdir(parents=True, exist_ok=True)
                publisher = DiscordPublisher(profile, Store(profile/'alerts.sqlite3'))
                publisher.store.recover()
                save_secret(self.alerts_credentials, json.dumps(dict(environment=environment, account=account, key=key, secret=secret)))
                self.publisher = publisher
                self.broker, self.account, self.environment, self.mode = broker, account, environment, 'alerts'
                self.alert_state = {'state':'connecting'}
                self.stop = asyncio.Event()
                enrollment = asyncio.create_task(self.poll_alerts())
                await asyncio.shield(enrollment)
                if self.start_workers:
                    self.tasks = [asyncio.create_task(self.discord_loop(self.stop))]
            except BaseException:
                # Cancellation cannot close a client while its threaded GET is running.
                if enrollment:
                    await asyncio.gather(enrollment, return_exceptions=True)
                broker.close()
                self.publisher = previous_publisher
                self.broker = None
                self.mode, self.account, self.environment = 'disconnected', '', ''
                self.alert_state = {'state':'stopped'}
                raise
            return self.status()

    def retry_rejected(self):
        if not self.device: raise ValueError('Connect first.')
        return self.device.retry_rejected()

    def discord_retry(self, identity):
        return self.publisher.retry(identity)

    def discord_close(self, identity):
        return self.publisher.close(identity)

    async def discord_loop(self, stop):
        with httpx.Client(trust_env=False,follow_redirects=False) as client:
            while not stop.is_set():
                await self.poll_alerts()
                if stop.is_set(): break
                await asyncio.to_thread(self.publisher.deliver,client)
                try: await asyncio.wait_for(stop.wait(),2)
                except TimeoutError: pass

    async def connect(self, pairing_text, key, secret, allow_live=False):
        async with self.lifecycle:
            self.require_disconnected()
            saved = json.loads(load_secret(self.credentials)) if self.credentials.exists() else {}
            try:
                pair = Pair.model_validate(json.loads(pairing_text) if pairing_text.strip() else
                    saved.get('pair') or self.connection_client().saved() or {}).model_dump()
            except (ValueError, TypeError):
                raise ValueError('Paste the complete host or follower pairing JSON.') from None
            provisional=self.connection_client().saved()
            if provisional and pair!=provisional:
                raise ValueError('This device is pinned to its saved pairing; replacing it would abandon its journal.')
            service_url(pair['url'])
            if not 32 <= len(pair['token']) <= 256:
                raise ValueError('Pairing must contain an HTTPS service address and valid token.')
            if pair['environment'] == 'live' and not allow_live:
                raise ValueError('Select Allow live account to connect a live pairing.')
            if bool(key.strip()) != bool(secret.strip()):
                raise ValueError('Enter both credentials, or leave both blank to reuse saved credentials.')
            key, secret = (key.strip(), secret.strip()) if key.strip() else (saved.get('key', ''), saved.get('secret', ''))
            account = await self.account_lookup(pair['environment'], key, secret)
            if saved and (saved['account'] != account or saved['pair'] != pair):
                raise ValueError('This desktop journal is pinned to its original account and channel. Reuse that pairing.')
            broker = self.broker_factory(pair['environment'], key, secret, account)
            try:
                device = IntentDevice(self.folder/'journal', broker)
                device.configure(pair)
                device.engine.save_settings({'enabled': False})
                save_secret(self.credentials, json.dumps(dict(pair=pair, key=key, secret=secret, account=account)))
            except Exception:
                broker.close()
                raise
            self.device, self.broker, self.account = device, broker, account
            self.environment, self.mode = pair['environment'], 'intent'
            self.publisher = self.intent_publisher
            # Enroll pre-existing activity silently before the user enables orders.
            await self.poll_alerts()
            self.stop = asyncio.Event()
            if self.start_workers:
                self.tasks = [asyncio.create_task(device.publish_loop(self.stop)),
                              asyncio.create_task(device.receive_loop(self.stop)),
                              asyncio.create_task(device.execute_loop(self.stop)),
                              asyncio.create_task(device.diagnostics_loop(self.stop)),
                              asyncio.create_task(self.discord_loop(self.stop))]
            return self.status()

    def status(self):
        state = self.device.status() if self.device else {'pair': {}, 'execution': None, 'message': 'Disconnected'}
        recovery = 'Reconnect with the same account and channel. New entries start paused; existing orders reconcile automatically.'
        if self.mode == 'alerts':
            state['message'] = 'Account read access verified. Fill monitor: ' + self.alert_state['state']
            recovery = 'Reconnect with the same account and environment. Saved fill cursor and Discord delivery history are retained.'
        return dict(state, connected=self.broker is not None and not self.closing, mode=self.mode, environment=self.environment,
                    account=self.account, saved=self.credentials.exists(), saved_alerts=self.alerts_credentials.exists(),
                    runtime='foreground' if self.broker else 'stopped',
                    alerts=self.alert_state,
                    recovery=recovery)

    async def diagnostics(self, trade_id, side='buy'):
        if not self.device or self.closing:
            raise ValueError('Connect first.')
        return await asyncio.to_thread(self.device.trade_report, trade_id, side)

    async def export_diagnostics(self, trade_id, format='json', side='buy'):
        if not self.device or self.closing:
            raise ValueError('Connect first.')
        return await asyncio.to_thread(self.device.export_trade, trade_id, format, side)

    def settings(self, settings):
        if not self.device or self.closing:
            raise ValueError('Connect first.')
        result = self.device.engine.save_settings(settings)
        self.device.changed.set()
        return result

    def command(self, action, **values):
        if not self.device or self.closing:
            raise ValueError('Connect first.')
        return self.device.command(action, **values).to_dict()

    async def disconnect(self):
        async with self.lifecycle:
            if not self.broker:
                return
            self.closing = True
            try:
                self.stop.set()
                if self.device:
                    self.device.engine.save_settings({'enabled': False})
                    self.device.changed.set()
                    self.device.publish_changed.set()
                    for task in self.tasks[:2] + self.tasks[3:4]:
                        task.cancel()
                # Do not cancel a to_thread broker mutation while it is committing.
                await asyncio.gather(*self.tasks, return_exceptions=True)
                async with self.alert_poll:
                    self.broker.close()
                self.mode, self.environment, self.account = 'disconnected', '', ''
                self.alert_state = {'state':'stopped'}
                self.device = None
                self.broker = None
                self.tasks = []
            finally:
                self.closing = False


class DesktopWorker:
    """Bridge Tk to the asyncio loop without executing UI calls off the Tk thread."""
    def __init__(self, folder):
        self.loop = asyncio.new_event_loop()
        self.session = DesktopSession(folder)
        self.thread = threading.Thread(target=self.loop.run_forever, name='Crier desktop', daemon=False)
        self.thread.start()

    def call(self, method, *args, **kwargs) -> Future:
        async def invoke():
            result = getattr(self.session, method)(*args, **kwargs)
            return await result if asyncio.iscoroutine(result) else result
        return asyncio.run_coroutine_threadsafe(invoke(), self.loop)

    def close(self):
        self.call('disconnect').result()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.loop.close()

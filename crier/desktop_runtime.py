"""Desktop lifecycle. All methods run on one background asyncio loop."""
import asyncio
from datetime import datetime, timezone
from concurrent.futures import Future
import json
import hashlib
import os
import sqlite3
from pathlib import Path
import threading
from .service_url import service_url

import httpx

from .device_secrets import load_secret, save_secret
from .intent_broker import AlpacaIntentBroker, HOSTS, alpaca_headers
from .intent_device import IntentDevice
from .intent_routes import Pair
from .connection_client import ConnectionClient
from .store import Store
from .discord_settings import DiscordPublisher
from .component_health import ComponentHealth
from .error_log import ErrorLog, emit_error, emit_event


def data_directory():
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()/'.local/share'))) / 'SentinelCrier' / 'Desktop'


async def discover_account(environment, key, secret, client=None, *, bearer=''):
    if environment not in HOSTS:
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers=alpaca_headers(key,secret,bearer=bearer), follow_redirects=False)
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


async def discover_alerts_account(environment, key, secret, client=None, *, bearer=''):
    """Verify read access; trading permission is irrelevant for fill monitoring."""
    from .alpaca import _identity
    if environment not in HOSTS:
        raise ValueError('Select an environment and enter both Alpaca credentials.')
    owned = client is None
    client = client or httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False)
    try:
        response = await client.get(HOSTS[environment]+'/v2/account', headers=alpaca_headers(key,secret,bearer=bearer), follow_redirects=False)
        response.raise_for_status()
        return _identity(response.json().get('id'))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ValueError('Cannot verify Alpaca read access. Check credentials, environment and connection.') from None
    finally:
        if owned:
            await client.aclose()


class AlpacaFillReader:
    """Read-only account adapter: deliberately has no order mutation methods."""
    def __init__(self, environment, key, secret, account, *, bearer=''):
        self.environment, self.account = environment, account
        self.client = httpx.Client(headers=alpaca_headers(key,secret,bearer=bearer),
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
                 alerts_lookup=discover_alerts_account, alerts_factory=AlpacaFillReader, error_log=None):
        self.error_log=error_log; self.last_log_health={}
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.health_error=False
        try:
            self.health=ComponentHealth(self.folder/'component-health.sqlite3')
            self.health_scope=self.health.latest_scope()
        except (OSError,sqlite3.Error):
            self.health=None; self.health_scope='unconfigured'; self.health_error=True
        self.credentials = self.folder/'desktop-credentials.secret'
        self.alerts_credentials = self.folder/'desktop-alerts-credentials.secret'
        self.alerts_lookup, self.alerts_factory = alerts_lookup, alerts_factory
        self.oauth = None
        self.oauth_jobs = set()
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
        self.auth_closing = False
        self.lifecycle = asyncio.Lock()
        self.intent_publisher=DiscordPublisher(self.folder,Store(self.folder/"alerts.sqlite3"))
        self.intent_publisher.observe=self.observe
        self.publisher = self.intent_publisher
        self.publisher.store.recover()
        self.alert_state={'state':'stopped'}
        self.discord_authorized = False

    def observe(self, component, state, reason):
        previous=self.last_log_health.get(component)
        if previous!=(state,reason):
            self.last_log_health[component]=(state,reason)
            emit_event(self.error_log,'health.'+component+'.'+state+'.'+reason,environment=self.environment)
        if self.health is None: return
        try:
            self.health.record(self.health_scope,component,state,reason)
            self.health_error=False
        except (OSError,sqlite3.Error): self.health_error=True

    def begin_health(self, environment, account, pair=None):
        self.health_scope=hashlib.sha256(json.dumps([environment,account,pair],sort_keys=True).encode()).hexdigest()
        if self.health: self.health.begin_session()
        self.observe('broker','healthy','verified')

    def component_status(self):
        active=set()
        if self.broker and not self.closing and not self.auth_closing:
            active.add('broker')
            if hasattr(self.broker,'client'): active.add('fills')
            if self.device:
                active.add('execution')
                active.add('relay_send' if self.device.pair['role']=='host' else 'relay_receive')
            if self.discord_authorized: active.add('discord')
        try: return self.health.snapshot(self.health_scope,active) if self.health else []
        except (OSError,sqlite3.Error): self.health_error=True; return []

    def provider_client(self):
        if self.oauth is None:
            from .provider_client import ProviderClient
            from .connection_client import default_origin
            default = default_origin()
            base = os.getenv('CRIER_OAUTH_SERVICE_URL',default+'-oauth' if default.endswith('/crier') else '')
            self.oauth = ProviderClient(base,self.folder/'customer-session.secret')
        return self.oauth

    async def provider_capabilities(self):
        return await self.provider_client().capabilities()

    async def customer_login(self, email, password, signup=False):
        async with self.lifecycle:
            self.require_disconnected()
            return await self.provider_client().login(email,password,signup=signup)

    async def customer_refresh(self):
        async with self.lifecycle:
            self.require_disconnected()
            await self.provider_client().refresh()
            return {'message':'Customer session renewed.'}

    async def stop_oauth_jobs(self):
        if self.oauth: self.oauth.invalidate()
        jobs=[task for task in self.oauth_jobs if task is not asyncio.current_task()]
        for task in jobs: task.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)

    async def customer_logout(self):
        self.auth_closing=True
        try:
            await self.stop_oauth_jobs()
            await self.disconnect()
            if self.oauth:
                result = await self.oauth.logout()
            else:
                (self.folder/'customer-session.secret').unlink(missing_ok=True)
                result = {'message':'Signed out.'}
            return result
        finally:
            self.auth_closing=False

    def oauth_identity(self):
        from uuid import UUID
        from .provider_client import validate_service
        client=self.provider_client()
        try:
            return {'service_url':validate_service(client.base),'owner':str(UUID(client.session['user']['id']))}
        except (TypeError,KeyError,AttributeError,ValueError):
            raise ValueError('OAuth customer sign-in required for saved provider credentials.') from None

    def require_oauth_owner(self, row):
        if row.get('bearer') or row.get('credential_mode')=='oauth' or 'oauth' in row:
            identity=self.oauth_identity()
            if row.get('oauth')!=identity:
                raise ValueError('OAuth customer or service differs from saved credentials; restore the original sign-in.')

    async def provider_begin(self, provider, purpose, environment):
        self.require_disconnected()
        capabilities=await self.provider_capabilities()
        if provider not in capabilities['providers']: raise ValueError('Provider unavailable.')
        launch=await self.provider_client().begin(provider,'alerts' if provider=='discord' else purpose,environment)
        self.provider_destination = 'alerts' if purpose=='alerts' else 'intent'
        return launch

    async def provider_cancel(self):
        if self.oauth: await self.oauth.cancel()
        return {'message':'Provider connection cancelled.'}

    async def provider_complete(self, uri):
        async with self.lifecycle:
            self.require_disconnected()
            client=self.provider_client()
            generation=client.generation
            identity=self.oauth_identity()
            grant=await client.complete(uri)
            if grant['provider']=='discord':
                if self.provider_destination=='alerts':
                    if not self.alerts_credentials.exists():
                        raise ValueError('Connect an alerts account once before installing Discord.')
                    saved=json.loads(load_secret(self.alerts_credentials))
                    if saved['environment']!=grant['environment']: raise ValueError('Discord environment mismatch.')
                    scope=hashlib.sha256(json.dumps([saved['environment'],saved['account']]).encode()).hexdigest()
                    profile=self.folder/'alerts-profiles'/scope
                    publisher=DiscordPublisher(profile,Store(profile/'alerts.sqlite3'))
                    allow_initial=True
                else:
                    if not self.credentials.exists(): raise ValueError('Connect a trading account once before installing Discord.')
                    saved=json.loads(load_secret(self.credentials))
                    if saved['pair']['environment']!=grant['environment']: raise ValueError('Discord environment mismatch.')
                    publisher=self.intent_publisher
                    allow_initial=False
                self.require_oauth_owner(saved)
                self.require_oauth_owner(publisher.destination)
                publisher.configure(grant['credential'],False,allow_initial=allow_initial,oauth=identity)
            else:
                trade=grant['purpose']=='trade'
                path=self.credentials if trade else self.alerts_credentials
                saved=json.loads(load_secret(path)) if path.exists() else {}
                self.require_oauth_owner(saved)
                if trade:
                    pair=saved.get('pair') or self.connection_client().saved()
                    if not pair: raise ValueError('Create or receive your pairing before authorizing trading.')
                    if pair['environment']!=grant['environment']: raise ValueError('Pairing environment mismatch.')
                lookup=self.account_lookup if trade else self.alerts_lookup
                account=await lookup(grant['environment'],'','',bearer=grant['credential'])
                if generation!=client.generation: raise ValueError('Customer session changed.')
                if account!=grant['account_id']: raise ValueError('Provider account verification mismatch.')
                if saved and (saved['account']!=account or (saved['pair']['environment'] if trade else saved['environment'])!=grant['environment']):
                    raise ValueError('Saved recovery records require the original account and environment.')
                if trade:
                    journal=self.folder/'journal'
                    pairing=journal/'intent-pairing.secret'
                    if pairing.exists() and json.loads(load_secret(pairing))!=pair:
                        raise ValueError('Journal pairing mismatch.')
                    import sqlite3
                    for database in journal.glob('intent-*.sqlite3'):
                        if database.name=='intent-device.sqlite3': continue
                        with sqlite3.connect(database) as db:
                            pin=db.execute('SELECT environment,account FROM intent_pin WHERE id=1').fetchone()
                            if pin and tuple(pin)!=(grant['environment'],account):
                                raise ValueError('Journal account/environment mismatch.')
                row=dict(account=account,key='',secret='',bearer=grant['credential'],oauth=identity)
                row.update({'pair':pair} if trade else {'environment':grant['environment']})
                save_secret(path,json.dumps(row))
            return {'message':'Provider connection saved. Reconnect explicitly; orders and delivery remain disabled.'}

    async def shutdown(self):
        await self.stop_oauth_jobs()
        await self.disconnect()
        if self.oauth: await self.oauth.close()
        if self.error_log:
            emit_event(self.error_log,'desktop.shutdown')
            await asyncio.to_thread(self.error_log.close)

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
        status = self.publisher.status()
        return status | dict(saved_enabled=status['enabled'], enabled=status['enabled'] and self.discord_authorized)

    def require_connected_publisher(self):
        if not self.broker or self.closing or self.auth_closing:
            raise ValueError('Connect and verify an account before changing Discord setup.')

    async def discord_configure(self, webhook, enabled):
        async with self.lifecycle:
            self.require_connected_publisher()
            original=self.publisher.destination
            reuse=not webhook.strip() or webhook.strip()==original['webhook']
            if reuse: self.require_oauth_owner(original)
            self.publisher.configure(webhook, enabled, allow_initial=self.mode == 'alerts')
            self.discord_authorized = enabled
            return self.discord_status()

    async def discord_settings(self, settings):
        async with self.lifecycle:
            self.require_connected_publisher()
            previous = self.publisher.status()['revision']
            result = self.publisher.settings(settings)
            if previous != self.publisher.status()['revision']:
                self.discord_authorized = False
            return result

    def discord_preview(self, scenario='option_buy', settings=None):
        return self.publisher.preview(scenario,settings)

    async def discord_test(self):
        async with self.lifecycle:
            self.require_connected_publisher()
            publisher = self.publisher
            self.require_oauth_owner(publisher.destination)
            def send():
                with httpx.Client(trust_env=False,follow_redirects=False) as client:
                    return publisher.test_message(client)
            # Keep the profile stable and wait for threaded delivery even on cancellation.
            delivery = asyncio.create_task(asyncio.to_thread(send))
            try:
                return await asyncio.shield(delivery)
            except asyncio.CancelledError:
                await asyncio.gather(delivery, return_exceptions=True)
                raise

    async def poll_alerts(self):
        from .alpaca import poll_once
        async with self.alert_poll:
            if not self.broker or not hasattr(self.broker,'client'): return
            broker, account = self.broker, self.account
            def poll():
                try: broker.verify(broker.environment)
                except Exception as exc:
                    auth=isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in (401,403)
                    self.observe('broker','blocked' if auth else 'degraded','authentication_failed' if auth else 'connection_failed')
                    raise
                self.observe('broker','healthy','verified')
                return poll_once(self.publisher.store,broker.client,account,broker.environment)
            try:
                self.alert_state=await asyncio.to_thread(poll)
                self.observe('fills','healthy','checked')
            except Exception:
                self.observe('fills','degraded','connection_failed')
                self.alert_state={'state':'reconnecting','message':'Fill activity unavailable; saved cursor retained. No inferred fills published.'}

    def require_disconnected(self):
        if self.broker or self.device or self.closing or self.auth_closing:
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
            if saved.get('bearer') and not key: self.require_oauth_owner(saved)
            bearer = saved.get('bearer','') if not key else ''
            account = await self.alerts_lookup(environment, key, secret, **({'bearer':bearer} if bearer else {}))
            if saved and saved['account'] != account:
                raise ValueError('Alerts monitoring is pinned to its original account.')
            broker = self.alerts_factory(environment, key, secret, account, **({'bearer':bearer} if bearer else {}))
            previous_publisher = self.publisher
            enrollment = None
            try:
                scope = hashlib.sha256(json.dumps([environment, account]).encode()).hexdigest()
                profile = self.folder/'alerts-profiles'/scope
                profile.mkdir(parents=True, exist_ok=True)
                publisher = DiscordPublisher(profile, Store(profile/'alerts.sqlite3'))
                publisher.store.recover()
                save_secret(self.alerts_credentials, json.dumps(dict(environment=environment, account=account, key=key, secret=secret, **({'bearer':bearer,'oauth':saved['oauth']} if bearer else {}))))
                self.publisher = publisher
                publisher.observe=self.observe
                self.broker, self.account, self.environment, self.mode = broker, account, environment, 'alerts'
                self.begin_health(environment,account)
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
                await asyncio.to_thread(self.deliver_alerts,client)
                try: await asyncio.wait_for(stop.wait(),2)
                except TimeoutError: pass

    def deliver_alerts(self, client):
        if self.discord_authorized and not self.closing and not self.auth_closing:
            try: self.require_oauth_owner(self.publisher.destination)
            except ValueError:
                self.observe('discord','blocked','customer_required')
                return False
            return self.publisher.deliver(client)
        return False

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
            if saved.get('bearer') and not key: self.require_oauth_owner(saved)
            bearer = saved.get('bearer','') if not key else ''
            account = await self.account_lookup(pair['environment'], key, secret, **({'bearer':bearer} if bearer else {}))
            if saved and (saved['account'] != account or saved['pair'] != pair):
                raise ValueError('This desktop journal is pinned to its original account and channel. Reuse that pairing.')
            broker = self.broker_factory(pair['environment'], key, secret, account, **({'bearer':bearer} if bearer else {}))
            try:
                device = IntentDevice(self.folder/'journal', broker, error_log=self.error_log)
                device.configure(pair)
                device.engine.save_settings({'enabled': False})
                save_secret(self.credentials, json.dumps(dict(pair=pair, key=key, secret=secret, account=account, **({'bearer':bearer,'oauth':saved['oauth']} if bearer else {}))))
            except Exception:
                broker.close()
                raise
            self.device, self.broker, self.account = device, broker, account
            self.environment, self.mode = pair['environment'], 'intent'
            self.begin_health(pair['environment'],account,pair)
            device.observe=self.observe
            self.publisher = self.intent_publisher
            # Enroll pre-existing activity silently before the user enables orders.
            await self.poll_alerts()
            self.stop = asyncio.Event()
            if self.start_workers:
                self.tasks = [asyncio.create_task(device.publish_loop(self.stop)),
                              asyncio.create_task(device.receive_loop(self.stop)),
                              asyncio.create_task(device.execute_loop(self.stop)),
                              asyncio.create_task(device.diagnostics_loop(self.stop)),
                              asyncio.create_task(device.reports_loop(self.stop)),
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
                    alerts=self.alert_state, health=self.component_status(), health_error=self.health_error,
                    technical_logging=self.error_log.status() if self.error_log else None,
                    recovery=recovery)

    async def diagnostics(self, trade_id, side='buy'):
        if not self.device or self.closing or self.auth_closing:
            raise ValueError('Connect first.')
        return await asyncio.to_thread(self.device.trade_report, trade_id, side)

    async def connection_test(self):
        from .customer_readiness import probe_connection
        async with self.lifecycle:
            if not self.broker or self.closing or self.auth_closing:
                return {'ready':False,'rows':[{'component':'broker','status':'failed','code':'connect_first'}],
                        'delivery':'not_tested'}
            environment=self.environment
            pair=dict(self.device.pair) if self.device and self.device.pair else None
            task=asyncio.create_task(probe_connection(self.broker,environment,self.account,pair,
                require_trading=self.mode != "alerts"))
            try:
                result=await asyncio.shield(task)
                return {**result,'environment':environment,'checked_at':datetime.now(timezone.utc).isoformat()}
            except asyncio.CancelledError:
                # Cancel and drain the bounded reader before disconnect proceeds.
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                raise

    async def export_diagnostics(self, trade_id, format='json', side='buy'):
        if not self.device or self.closing or self.auth_closing:
            raise ValueError('Connect first.')
        return await asyncio.to_thread(self.device.export_trade, trade_id, format, side)

    async def support_bundle(self,path):
        if not self.error_log: raise ValueError('Technical logging is unavailable in this session.')
        return await asyncio.to_thread(self.error_log.export,path)

    def settings(self, settings):
        if not self.device or self.closing or self.auth_closing:
            raise ValueError('Connect first.')
        result = self.device.engine.save_settings(settings)
        self.device.changed.set()
        return result

    def command(self, action, **values):
        if not self.device or self.closing or self.auth_closing:
            raise ValueError('Connect first.')
        return self.device.command(action, **values).to_dict()

    async def disconnect(self):
        async with self.lifecycle:
            if not self.broker:
                return
            self.closing = True
            self.discord_authorized = False
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
        self.error_log=ErrorLog(Path(folder)/'runtime-logs')
        from .desktop_connections import DesktopConnections
        self.connections = DesktopConnections(folder)
        emit_event(self.error_log,'desktop.started')
        self.loop.set_exception_handler(lambda loop,context:emit_error(self.error_log,'desktop.async_failure',context.get('exception') or RuntimeError()))
        self.thread = threading.Thread(target=self.loop.run_forever, name='Crier desktop', daemon=False)
        self.thread.start()

    @property
    def session(self):
        return self.connections.session

    def call(self, method, *args, **kwargs) -> Future:
        identity = self.connections.selected
        async def invoke():
            try:
                return await self.connections.invoke(identity, method, *args, **kwargs)
            except Exception as exc:
                emit_error(self.connections.sessions[identity].error_log, 'desktop.operation_failed', exc)
                raise
        future = asyncio.run_coroutine_threadsafe(invoke(), self.loop)
        future.route_id = identity
        return future

    def close(self):
        self.call('shutdown').result()
        self.error_log.close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.loop.close()

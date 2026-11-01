"""Installs verified provider grants without exposing the desktop session."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import hashlib
import json
from .device_secrets import load_secret, save_secret
from .discord_settings import DiscordPublisher
from .store import Store


@dataclass(frozen=True)
class ProviderGrantInstaller:
    folder: Path
    credentials: Path
    alerts_credentials: Path
    destination: str
    intent_publisher: DiscordPublisher
    require_oauth_owner: Callable
    account_lookup: Callable
    alerts_lookup: Callable
    saved_pair: Callable
    generation: Callable

    async def install(self, grant, identity, generation):
        if grant['provider']=='discord':
            if self.destination=='alerts':
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
                pair=saved.get('pair') or self.saved_pair()
                if not pair: raise ValueError('Create or receive your pairing before authorizing trading.')
                if pair['environment']!=grant['environment']: raise ValueError('Pairing environment mismatch.')
            lookup=self.account_lookup if trade else self.alerts_lookup
            account=await lookup(grant['environment'],'','',bearer=grant['credential'])
            if generation!=self.generation(): raise ValueError('Customer session changed.')
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

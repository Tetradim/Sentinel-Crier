"""One durable publisher for desktop and browser settings and explicit test sends."""
import json
import hashlib
import time
from pathlib import Path
from uuid import uuid4

from .cards import render
from .delivery import deliver_once, validate_webhook
from .device_secrets import load_secret, save_secret
from .models import Settings
from .samples import sample


class DiscordPublisher:
    def __init__(self, folder, store, webhook='', enabled=False):
        self.path=Path(folder)/'discord-destination.secret'
        self.store=store
        self.destination=json.loads(load_secret(self.path)) if self.path.exists() else dict(webhook=webhook,enabled=enabled)

    def configure(self, webhook, enabled, *, allow_initial=False, oauth=None):
        if type(enabled) is not bool: raise ValueError('Select whether delivery is enabled')
        webhook=webhook.strip() or self.destination['webhook']
        validate_webhook(webhook)
        destination=dict(webhook=webhook,enabled=enabled)
        # Reusing a saved webhook cannot silently turn OAuth into manual setup.
        if oauth is None and webhook==self.destination['webhook'] and ('oauth' in self.destination or self.destination.get('credential_mode')=='oauth'):
            oauth=self.destination.get('oauth')
            if oauth is None: raise ValueError('Missing OAuth customer provenance')
        if oauth is not None:
            from uuid import UUID
            from .provider_client import validate_service
            try:
                if not isinstance(oauth,dict) or set(oauth)!={'service_url','owner'}: raise ValueError()
                validate_service(oauth['service_url'])
                if str(UUID(oauth['owner']))!=oauth['owner']: raise ValueError()
            except (ValueError,TypeError,AttributeError,KeyError):
                raise ValueError('Invalid OAuth customer provenance') from None
            destination.update(credential_mode='oauth',oauth=dict(oauth))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            queued=db.execute("SELECT COUNT(*) FROM outbox WHERE status IN ('pending','sending','uncertain','review','failed')").fetchone()[0]
            initial = allow_initial and not self.destination['webhook'] and not self.path.exists()
            if initial:
                unsafe=db.execute("SELECT COUNT(*) FROM outbox WHERE status!='pending' OR attempts!=0 OR attempts IS NULL OR status IS NULL").fetchone()[0]
                prior=db.execute("SELECT 1 FROM config WHERE id='discord_destination_configured'").fetchone()
                if unsafe or prior:
                    raise ValueError('Cannot assign a first destination to prior delivery evidence. Restore the original destination secret.')
            if queued and webhook!=self.destination['webhook'] and not initial:
                raise ValueError('Resolve queued or uncertain alerts before changing the Discord destination')
            save_secret(self.path,json.dumps(destination))
            db.execute("INSERT OR REPLACE INTO config VALUES ('discord_destination_configured','true')")
        self.destination=destination
        return self.status()

    def status(self):
        settings = self.store.get_settings().model_dump()
        # No destination secret is returned; presentation changes invalidate setup evidence.
        presentation = {key: value for key, value in settings.items() if key != 'paused'}
        revision = hashlib.sha256(json.dumps([self.destination['webhook'], presentation], sort_keys=True, default=str).encode()).hexdigest()
        return dict(configured=bool(self.destination['webhook']),enabled=self.destination['enabled'],
                    revision=revision, settings=settings,history=self.store.history())

    def settings(self, values):
        settings=Settings.model_validate(values)
        self.store.save_settings(settings)
        return settings.model_dump()

    def preview(self, scenario='option_buy', settings=None):
        return render(sample(scenario), Settings.model_validate(settings) if settings else self.store.get_settings())

    def deliver(self, client):
        if not self.destination['enabled'] or self.store.get_settings().paused: return False
        return deliver_once(self.store,self.destination['webhook'],client)

    def retry(self, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM outbox WHERE id=?',(identity,)).fetchone()
            if not row or row['status']!='failed':
                raise ValueError('Only definitively failed messages can retry. Check uncertain delivery in Discord; it is never automatically replayed.')
            db.execute("UPDATE outbox SET status='pending',attempts=0,due=0,note='Explicit retry requested' WHERE id=?",(identity,))
        return next(row for row in self.store.history() if row['id']==identity)

    def close(self, identity):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM outbox WHERE id=?',(identity,)).fetchone()
            if not row or row['status'] not in ('pending','failed','uncertain','review'):
                raise ValueError('Only pending, failed, uncertain or review messages can be closed. Sending and delivered messages retain their status.')
            note=(row['note']+'; ' if row['note'] else '')+'User closed after review; no resend. Previous state: '+row['status']
            db.execute("UPDATE outbox SET status='closed',note=? WHERE id=?",(note,identity))
            closed=dict(row)
        return closed | dict(status='closed',note=note,fill=json.loads(row['fill']),payload=json.loads(row['payload']))

    def test_message(self, client):
        validate_webhook(self.destination['webhook'])
        identity='test-'+str(uuid4())
        payload=self.preview()
        payload['content']='TEST • Synthetic preview only. No order or broker fill.' + ('\n'+payload['content'] if payload.get('content') else '')
        fill=sample('option_buy')
        fill.update(contract='TEST message',side='TEST',quantity='0',price='0',verification='synthetic')
        with self.store.connect() as db:
            db.execute('INSERT INTO outbox(id,created,fill,payload) VALUES (?,?,?,?)',
                       (identity,time.time(),json.dumps(fill),json.dumps(payload)))
        # A test action sends only this job; it never drains old live alerts.
        deliver_once(self.store,self.destination['webhook'],client,job_id=identity)
        return next(row for row in self.store.history() if row['id']==identity)

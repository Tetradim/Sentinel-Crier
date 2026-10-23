"""One durable publisher for desktop and browser settings and explicit test sends."""
import json
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

    def configure(self, webhook, enabled):
        if type(enabled) is not bool: raise ValueError('Select whether delivery is enabled')
        webhook=webhook.strip() or self.destination['webhook']
        validate_webhook(webhook)
        with self.store.connect() as db:
            queued=db.execute("SELECT COUNT(*) FROM outbox WHERE status IN ('pending','sending','uncertain','review','failed')").fetchone()[0]
        if queued and webhook!=self.destination['webhook']:
            raise ValueError('Resolve queued or uncertain alerts before changing the Discord destination')
        self.destination=dict(webhook=webhook,enabled=enabled)
        save_secret(self.path,json.dumps(self.destination))
        return self.status()

    def status(self):
        return dict(configured=bool(self.destination['webhook']),enabled=self.destination['enabled'],
                    settings=self.store.get_settings().model_dump(),history=self.store.history())

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

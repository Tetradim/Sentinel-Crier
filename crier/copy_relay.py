"""Authenticated observational storage. This module cannot submit orders."""
from datetime import datetime, timezone
import json
from .copy_dashboard import validate_status_binding
from .intent_protocol import IntentEvent


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS copy_presence(channel TEXT,actor TEXT,payload TEXT,received_at TEXT,PRIMARY KEY(channel,actor));
    CREATE TABLE IF NOT EXISTS copy_status(channel TEXT,trade_id TEXT,actor TEXT,event_sequence INTEGER,payload TEXT,received_at TEXT,PRIMARY KEY(channel,trade_id,actor));
    ''')


def save(relay, token, report, *, presence=False):
    payload=json.dumps(report.model_dump(),sort_keys=True,separators=(',', ':'))
    now=datetime.now(timezone.utc).isoformat()
    with relay.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if presence:
            channel,actor,_=relay.diagnostic_identity(db,token)
            prior=db.execute('SELECT payload FROM copy_presence WHERE channel=? AND actor=?',(channel['id'],actor)).fetchone()
        else:
            channel,actor=relay.diagnostic_access(db,token,report.event_id)
            event=IntentEvent.model_validate_json(db.execute('SELECT payload FROM intents WHERE channel=? AND event_id=?',(channel['id'],report.event_id)).fetchone()[0])
            validate_status_binding(report,event.to_dict())
            prior=db.execute('SELECT payload,event_sequence FROM copy_status WHERE channel=? AND trade_id=? AND actor=?',(channel['id'],event.trade_id,actor)).fetchone()
        if prior:
            old=json.loads(prior['payload'])
            if old==json.loads(payload): return {'stored':True}
            if report.revision<=old['revision']: raise ValueError('Stale report revision')
            if not presence:
                if event.sequence<prior['event_sequence'] or report.bought<old['bought'] or report.sold<old['sold']:
                    raise ValueError('Report evidence cannot regress')
        if presence:
            db.execute('INSERT OR REPLACE INTO copy_presence VALUES (?,?,?,?)',(channel['id'],actor,payload,now))
        else:
            db.execute('INSERT OR REPLACE INTO copy_status VALUES (?,?,?,?,?,?)',(channel['id'],event.trade_id,actor,event.sequence,payload,now))
    return {'stored':True}


def snapshot(relay,token):
    with relay.db() as db:
        channel,actor,start=relay.diagnostic_identity(db,token)
        role='host' if actor=='host' else 'follower'
        members=[{'actor':'host','role':'host','revoked':False}]
        receivers=db.execute('SELECT id,revoked FROM receivers WHERE channel=? ORDER BY created',(channel['id'],)).fetchall()
        members.extend({'actor':r['id'],'role':'follower','revoked':bool(r['revoked'])} for r in receivers if actor=='host' or actor==r['id'])
        if actor=='legacy_receiver': members.append({'actor':actor,'role':'follower','revoked':False})
        for member in members:
            row=db.execute('SELECT payload,received_at FROM copy_presence WHERE channel=? AND actor=?',(channel['id'],member['actor'])).fetchone()
            member.update(presence=json.loads(row['payload']) if row else None,last_seen_at=row['received_at'] if row else None)
        rows=db.execute('''SELECT i.payload FROM intents i WHERE i.channel=? AND i.cursor>?
          AND NOT EXISTS (SELECT 1 FROM intents newer WHERE newer.channel=i.channel AND newer.trade_id=i.trade_id AND newer.sequence>i.sequence)
          ORDER BY i.cursor DESC LIMIT 51''',(channel['id'],start)).fetchall()
        events=[json.loads(r[0]) for r in rows[:50]]
        ids={e['event_id'] for e in events}
        statuses=[]; diagnostics=[]
        for r in db.execute('SELECT actor,payload,received_at FROM copy_status WHERE channel=? ORDER BY received_at DESC',(channel['id'],)):
            report=json.loads(r['payload'])
            if report['event_id'] in ids and (actor=='host' or r['actor'] in ('host',actor)):
                statuses.append(dict(actor=r['actor'],report=report,received_at=r['received_at']))
                if len(statuses)>200: break
        for r in db.execute('SELECT event_id,actor,observation FROM diagnostics WHERE channel=?',(channel['id'],)):
            if r['event_id'] in ids and (actor=='host' or r['actor'] in ('host',actor)):
                diagnostics.append(dict(event_id=r['event_id'],actor=r['actor'],observation=json.loads(r['observation'])))
                if len(diagnostics)>200: break
        return dict(version=1,channel_id=channel['id'],environment=channel['environment'],role=role,actor=actor,
                    generated_at=datetime.now(timezone.utc).isoformat(),members=members[:200],events=events,statuses=statuses[:200],
                    diagnostics=diagnostics[:200],truncated=len(rows)>50 or len(members)>200 or len(statuses)>200 or len(diagnostics)>200)

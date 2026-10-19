from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from crier.live_order_journal import LiveOrderJournal, LiveJournalError, OrderIntent, order_set_digest


def test_legacy_migration_preserves_unknown_orders_fills_and_audit(tmp_path):
    path = tmp_path / 'legacy.db'
    db = sqlite3.connect(path)
    db.executescript((Path(__file__).parent / 'fixtures/journal_v1.sql').read_text())
    group, client = str(uuid4()), str(uuid4())
    db.execute('INSERT INTO groups VALUES(?,?,?,?)', ('t', group, 'old', 'old'))
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               ('t', group, client, 'alpaca', 'a', 'contract', 'buyToOpen', 10,
                '1.23', 'partially_filled', 'broker-1', 2))
    db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)',
               ('t', 'alpaca', 'a', 'fill-1', client, 2, '1.20', '2026-10-16T15:00:00Z'))
    # Empty audit is valid for this schema fixture; populate a valid audit entry
    # through the same hash algorithm to verify it survives byte-for-byte.
    import hashlib, json
    digest = hashlib.sha256(json.dumps(['old', 't', 'legacy', '{}', 'GENESIS'], separators=(',', ':')).encode()).hexdigest()
    db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?)', (1, 'old', 't', 'legacy', '{}', 'GENESIS', digest))
    db.commit(); db.close()
    journal = LiveOrderJournal(path)
    try:
        assert journal.verify_audit_chain()
        assert journal._db.execute('SELECT entry_hash FROM audit WHERE seq=1').fetchone()[0] == digest
        row, = journal.orders_for_group('t', group)
        assert (row['state'], row['cumulative_filled'], row['broker_order_id']) == ('partially_filled', 2, 'broker-1')
        assert not journal.record_execution('t', client, 'fill-1', 2, '1.20', '2026-10-16T15:00:00+00:00', 'broker-1', broker_id='alpaca', account_id='a')
        with pytest.raises(LiveJournalError):
            journal.reserve_submission('t', client)
        assert journal._db.execute('PRAGMA user_version').fetchone()[0] == 2
    finally:
        journal.close()
    reopened = LiveOrderJournal(path)
    assert reopened.verify_audit_chain()
    reopened.close()


def test_expired_confirmation_can_renew_but_reserved_group_cannot(tmp_path):
    now = [1000.0]
    journal = LiveOrderJournal(tmp_path / 'renew.db', clock=lambda: now[0])
    order = OrderIntent('t', str(uuid4()), 'alpaca', 'a', 'contract', str(uuid4()), 'buyToOpen', 1, '1.00')
    try:
        journal.stage_group([order])
        digest = order_set_digest([order])
        journal.confirm_group('t', order.group_id, expected_digest=digest, ttl_seconds=1)
        now[0] += 2
        journal.confirm_group('t', order.group_id, expected_digest=digest, ttl_seconds=1)
        journal.reserve_submission('t', order.client_order_id)
        now[0] += 2
        with pytest.raises(LiveJournalError):
            journal.confirm_group('t', order.group_id, expected_digest=digest)
        assert journal.verify_audit_chain()
    finally:
        journal.close()


@pytest.mark.parametrize('state', ['submission_unknown', 'unsubmitted'])
def test_legacy_confirmation_requires_fresh_consent_and_never_retries_unknown(tmp_path, state):
    path = tmp_path / 'legacy-state.db'
    db = sqlite3.connect(path)
    db.executescript((Path(__file__).parent / 'fixtures/journal_v1.sql').read_text())
    group, client = str(uuid4()), str(uuid4())
    db.execute('INSERT INTO groups VALUES(?,?,?,?)', ('t', group, 'old', 'old'))
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               ('t', group, client, 'alpaca', 'a', 'contract', 'buyToOpen', 1,
                '1.23', state, None, 0))
    db.commit(); db.close()
    journal = LiveOrderJournal(path)
    try:
        with pytest.raises(LiveJournalError):
            journal.reserve_submission('t', client)
        digest = journal.group_digest('t', group)
        if state == 'submission_unknown':
            with pytest.raises(LiveJournalError):
                journal.confirm_group('t', group, expected_digest=digest)
        else:
            journal.confirm_group('t', group, expected_digest=digest)
            journal.reserve_submission('t', client)
        assert journal.orders_for_group('t', group)[0]['state'] == 'submission_unknown'
    finally:
        journal.close()


def test_migration_failure_rolls_back_all_schema_and_data_changes(tmp_path):
    path = tmp_path / 'orphan.db'
    db = sqlite3.connect(path)
    db.executescript((Path(__file__).parent / 'fixtures/journal_v1.sql').read_text())
    db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?,?,?)',
               ('t', 'alpaca', 'a', 'orphan', str(uuid4()), 1, '1.20', '2026-10-16T15:00:00Z'))
    db.commit()
    before = list(db.iterdump())
    db.close()
    with pytest.raises(LiveJournalError, match='no matching broker order'):
        LiveOrderJournal(path)
    db = sqlite3.connect(path)
    try:
        assert list(db.iterdump()) == before
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
    finally:
        db.close()

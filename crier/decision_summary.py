"""Bounded, read-only explanations of existing chronological execution evidence.

Only allowlisted messages are emitted. No input text or identifiers are displayed.
Rows use {"stage": str, "details": mapping | JSON object string}; callers supply
chronological order. A returned submission call never establishes a fill.
"""
import json
from collections.abc import Mapping

MESSAGES = {
    'journaled': 'The instruction was saved on this device.',
    'received': 'The instruction reached this device.',
    'relay_ack': 'The relay acknowledged the instruction; broker execution is not confirmed.',
    'relay_started': 'Sending the instruction to the relay was started; delivery is not confirmed.',
    'relay_rejected': 'The relay rejected the instruction; broker execution is not confirmed.',
    'started': 'A broker submission was started; the outcome is not confirmed.',
    'returned': 'The broker submission call returned; a fill is not confirmed.',
    'not_submitted': 'This attempt was not submitted to the broker.',
    'rejected': 'This submission was refused; a fill is not established by this record.',
    'unknown': 'The broker outcome is unknown. Reconciliation is required before new work.',
    'cancel_requested': 'Cancellation was requested; cancellation is not confirmed.',
    'canceled': 'The broker reports the order canceled; earlier fills may remain.',
    'partial': 'The broker reports a partial fill; the full order is not confirmed filled.',
    'filled': 'The broker reports the order filled.',
    'active': 'The broker reports an active order; a full fill is not confirmed.',
    'expired': 'The broker reports the order expired; earlier fills may remain.',
    'broker_evidence': 'Broker evidence was refreshed; the recorded outcome is not confirmed.',
    'skipped': 'The entry was skipped by local checks.',
    'deferred': 'The entry was deferred; no new submission is confirmed.',
    'clock': 'The entry was deferred because the device clock needs checking.',
    'future': 'The entry is waiting for its recorded start time.',
    'paused': 'The entry was skipped because new entries were paused.',
    'limit': 'The entry was skipped because a local quantity or age limit was reached.',
    'entry_expired': 'The entry was skipped because its instruction expired.',
    'invalidated': 'The entry remainder was invalidated; any recorded fills are retained.',
    'complete': 'Local instruction processing completed; a fill is not confirmed.',
    'execution_started': 'Local execution checks started; submission is not confirmed.',
    'other': 'Additional evidence was recorded; its meaning is unavailable.',
    'empty': 'No decision evidence is recorded yet.',
}

_STAGES = {
    'sender_instruction_journaled': 'journaled',
    'sender': 'journaled',
    'instruction_stored': 'journaled',
    'receiver_instruction_stored': 'journaled',
    'receiver_instruction_arrived': 'received',
    'receiver': 'received',
    'relay_publish_acknowledged': 'relay_ack',
    'relay_ack': 'relay_ack',
    'relay_accepted': 'relay_ack',
    'relay_publish_started': 'relay_started',
    'relay_publish_rejected': 'relay_rejected',
    'relay_rejected': 'relay_rejected',
    'broker_submit_started': 'started',
    'submit_attempt': 'started',
    'order_dispatch': 'started',
    'broker_submit_returned': 'returned',
    'broker_response': 'returned',
    'broker_not_submitted': 'not_submitted',
    'order_not_submitted': 'not_submitted',
    'broker_submit_superseded': 'not_submitted',
    'broker_submit_rejected': 'rejected',
    'broker_rejected': 'rejected',
    'broker_lookup_unknown': 'unknown',
    'broker_lookup_unusable': 'unknown',
    'execution_error': 'unknown',
    'cancel_uncertain': 'unknown',
    'reconciliation_wait': 'unknown',
    'reconciliation_error': 'unknown',
    'execution_pending': 'unknown',
    'cancel_requested': 'cancel_requested',
    'cancel_dispatch': 'cancel_requested',
    'entry_invalidated': 'invalidated',
    'execution_complete': 'complete',
    'execution_started': 'execution_started',
}

_STATUSES = {
    'new': 'active',
    'accepted': 'active',
    'pending_new': 'active',
    'accepted_for_bidding': 'active',
    'pending_replace': 'active',
    'partially_filled': 'partial',
    'filled': 'filled',
    'canceled': 'canceled',
    'pending_cancel': 'cancel_requested',
    'rejected': 'rejected',
    'expired': 'expired',
    'unknown': 'unknown',
    'submit_unknown': 'unknown',
    'cancel_unknown': 'unknown',
}

_STATES = {
    'reconcile_required': 'unknown',
    'waiting_for_reconciliation': 'unknown',
    'manual_reconcile': 'unknown',
    'cancel_pending': 'cancel_requested',
    'rejected': 'rejected',
    'skipped': 'skipped',
    'superseded': 'not_submitted',
    'invalidated': 'invalidated',
    'settled': 'complete',
    'submitted': 'returned',
    'waiting_for_clock': 'clock',
    'waiting_for_start': 'future',
}

_REASONS = {
    'clock_changed': 'clock',
    'future_created_at': 'future',
    'prior_order_evidence_unavailable': 'unknown',
    'entries_paused': 'paused',
    'expired': 'entry_expired',
    'max_quantity': 'limit',
    'age_or_revision_limit': 'limit',
    'too_old': 'limit',
}

def _details(value):
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and len(value) <= 16384:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, RecursionError):
            pass
    return {}


def _lookup(table, value, default):
    return table.get(value, default) if isinstance(value, str) else default


def _message(row):
    if not isinstance(row, Mapping):
        return MESSAGES['other']
    stage = row.get('stage')
    details = _details(row.get('details'))
    if stage in ('broker_reconciled', 'reconciled', 'order_state'):
        key = _lookup(_STATUSES, details.get('status'), 'broker_evidence')
    elif stage == 'execution_decision':
        key = _lookup(_STATES, details.get('state'), 'other')
    elif stage in ('entry_deferred', 'execution_deferred', 'entry_skipped'):
        key = _lookup(_REASONS, details.get('reason'), 'skipped' if stage == 'entry_skipped' else 'deferred')
    else:
        key = _lookup(_STAGES, stage, 'other')
    return MESSAGES[key]


def describe_decisions(timeline, limit=8):
    """Return the last 1..20 explanations, coalescing consecutive duplicates.

    Invalid limit types use eight. Empty/invalid timelines have one truthful
    placeholder. No storage, broker calls, or state changes occur here.
    """
    count = max(1, min(20, limit)) if type(limit) is int else 8
    if not isinstance(timeline, (list, tuple)) or not timeline:
        return [MESSAGES['empty']]
    result = []
    for row in timeline:
        message = _message(row)
        if not result or result[-1] != message:
            result.append(message)
            if len(result) > count:
                del result[0]
    return result

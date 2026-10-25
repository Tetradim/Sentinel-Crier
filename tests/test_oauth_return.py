import json
from pathlib import Path

import pytest

from crier.oauth_return import OAuthReturnContext, PendingOAuthReturn, parse_oauth_return


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/oauth-return.json').read_text())
FLOW = FIXTURE['flow']
URI = FIXTURE['canonical']
CONTEXT = OAuthReturnContext('owner-1', 'alpaca', 'paper', 'alerts')


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['name'])
def test_shared_canonical_uri_contract(case):
    assert parse_oauth_return(case['uri']) == (FLOW if case['valid'] else None)


def pending():
    return PendingOAuthReturn(FLOW, CONTEXT, expires_at=100)


def test_return_only_yields_trusted_local_context_once():
    value = pending()
    assert value.match_return(URI, FLOW, CONTEXT, now=99) is CONTEXT
    assert value.match_return(URI, FLOW, CONTEXT, now=99) is None


@pytest.mark.parametrize('field,replacement', [
    ('owner', 'owner-2'), ('provider', 'discord'),
    ('environment', 'live'), ('purpose', 'trade'),
])
def test_context_cannot_be_selected_by_uri_or_wrong_caller(field, replacement):
    from dataclasses import replace
    value = pending()
    assert value.match_return(URI, FLOW, replace(CONTEXT, **{field: replacement}), now=1) is None
    assert value.match_return(URI, FLOW, CONTEXT, now=1) is CONTEXT


def test_wrong_flow_and_malformed_returns_do_not_consume_pending():
    value = pending()
    assert value.match_return(URI, 'B' * 43, CONTEXT, now=1) is None
    assert value.match_return(URI + '&code=secret', FLOW, CONTEXT, now=1) is None
    assert value.match_return(URI.replace(FLOW, 'B' * 43), FLOW, CONTEXT, now=1) is None
    assert value.match_return(URI, FLOW, CONTEXT, now=1) is CONTEXT


@pytest.mark.parametrize('operation', ['cancel', 'invalidate', 'timeout', 'nonfinite'])
def test_terminal_states_cannot_accept_or_revive(operation):
    value = pending()
    if operation in ('cancel', 'invalidate'):
        getattr(value, operation)()
    else:
        assert value.match_return(URI, FLOW, CONTEXT, now=100 if operation == 'timeout' else float('nan')) is None
    assert value.match_return(URI, FLOW, CONTEXT, now=1) is None


def test_restart_has_no_pending_and_constructor_rejects_invalid_state():
    assert PendingOAuthReturn.match_pending(None, URI, FLOW, CONTEXT, now=1) is None
    with pytest.raises(ValueError):
        PendingOAuthReturn('short', CONTEXT, expires_at=100)
    with pytest.raises(ValueError):
        PendingOAuthReturn(FLOW, CONTEXT, expires_at=float('inf'))
    with pytest.raises(ValueError):
        OAuthReturnContext('owner', 'discord', 'live', 'trade')


def test_concurrent_replay_accepts_once():
    from concurrent.futures import ThreadPoolExecutor
    value = pending()
    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = list(pool.map(lambda _: value.match_return(URI, FLOW, CONTEXT, now=1), range(24)))
    assert sum(result is CONTEXT for result in accepted) == 1

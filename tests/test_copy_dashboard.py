from datetime import datetime,timezone
import json
from pathlib import Path
import pytest
from crier.copy_dashboard import StatusReport,PresenceReport,dashboard_metrics,validate_status_binding


def report(**changes):
    return dict(version=1,event_id='00000000-0000-4000-8000-000000000001',revision=1,
                observed_at='2026-10-26T12:00:00Z',state='received',bought=0,sold=0,**changes)


@pytest.mark.parametrize('case',json.loads((Path(__file__).parent/'fixtures/copy-dashboard.json').read_text())['cases'],ids=lambda c:c['id'])
def test_shared_dashboard_math(case):
    assert dashboard_metrics(**case['input'])==case['expected']


@pytest.mark.parametrize('patch',[{'version':True},{'revision':True},{'revision':0},{'revision':9007199254740992},
                                 {'actor':'someone-else'},{'state':'execute_now'},{'observed_at':'2026-10-26T12:00:00'},
                                 {'bought':True},{'sold':1},{'buy_premium':'NaN'},{'reason':'arbitrary secret'},
                                 {'currency':'USD'},{'multiplier':100}])
def test_status_strict_contract(patch):
    value=report();value.update(patch)
    with pytest.raises(ValueError):StatusReport.model_validate(value)


def test_metadata_must_match_source_asset():
    value=StatusReport.model_validate(report(currency='USD',multiplier=1))
    with pytest.raises(ValueError):validate_status_binding(value,{'asset':'option'})
    validate_status_binding(value,{'asset':'stock'})


def test_presence_has_no_actor_or_trade_authority():
    value=dict(version=1,revision=1,observed_at='2026-10-26T12:00:00Z',platform='windows',transport='push',entries_enabled=False)
    assert PresenceReport.model_validate(value).transport=='push'
    with pytest.raises(ValueError):PresenceReport.model_validate(dict(value,actor='host'))

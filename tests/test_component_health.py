from crier.component_health import ComponentHealth
import pytest


class Clock:
    wall = 1000.0
    mono = 10.0
    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


def ledger(tmp_path, clock):
    return ComponentHealth(tmp_path/'health.sqlite3', wall=lambda:clock.wall, monotonic=lambda:clock.mono)


def row(health, scope='account-a', active=('broker',)):
    return next(r for r in health.snapshot(scope, active) if r['component']=='broker')


def test_persisted_success_is_evidence_not_readiness_after_restart_or_reconnect(tmp_path):
    clock=Clock(); health=ledger(tmp_path,clock)
    assert row(health)['state']=='waiting'
    health.record('account-a','broker','healthy','verified')
    assert row(health)['state']=='healthy'
    reopened=ledger(tmp_path,clock)
    assert row(reopened)['state']=='waiting'
    assert row(reopened)['last_success']==1000
    health.begin_session()
    assert row(health)['state']=='waiting'
    assert row(health,active=())['state']=='stopped'


def test_account_scope_never_inherits_success_or_errors(tmp_path):
    health=ledger(tmp_path,Clock())
    health.record('account-a','broker','blocked','authentication_failed')
    assert row(health)['state']=='blocked'
    assert row(health,'account-b')['state']=='waiting'
    assert row(health,'account-b')['last_success'] is None


def test_latest_context_is_not_selected_by_a_skewed_wall_clock(tmp_path):
    clock=Clock(); health=ledger(tmp_path,clock)
    health.record('account-a','broker','healthy','verified')
    clock.wall-=100
    health.record('account-b','broker','healthy','verified')
    assert ledger(tmp_path,clock).latest_scope()=='account-b'


def test_staleness_and_clock_discontinuity_do_not_refresh_evidence(tmp_path):
    clock=Clock(); health=ledger(tmp_path,clock)
    health.record('account-a','broker','healthy','verified')
    clock.advance(61)
    assert row(health)['state']=='stale'
    clock.wall-=3600
    assert row(health)['state']=='clock_changed'
    assert row(health)['age_seconds']==61
    assert row(health)['last_success']==1000
    clock.wall+=7200
    assert row(health)['state']=='clock_changed'


def test_idle_is_not_an_ack_and_failure_preserves_last_success(tmp_path):
    clock=Clock(); health=ledger(tmp_path,clock)
    health.record('account-a','broker','idle','no_work')
    assert row(health)['state']=='idle'; assert row(health)['last_success'] is None
    health.record('account-a','broker','healthy','verified')
    clock.advance(3)
    health.record('account-a','broker','degraded','connection_failed')
    assert row(health)['state']=='degraded'; assert row(health)['last_success']==1000
    assert row(health)['reason']=='connection_failed'


@pytest.mark.parametrize('component,state,reason',[('private-token','healthy','verified'),('broker','secret','verified'),('broker','blocked','Bearer secret')])
def test_raw_secrets_and_unrecognized_statuses_are_rejected(tmp_path,component,state,reason):
    with pytest.raises(ValueError): ledger(tmp_path,Clock()).record('scope',component,state,reason)

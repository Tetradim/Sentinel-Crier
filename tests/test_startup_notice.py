import pytest

from crier.startup_notice import StartupNotice


AVAILABLE = {'status': 'available', 'version': '0.3.0', 'notes': 'A signed release is available.'}


def test_startup_check_runs_once_per_launch():
    notice = StartupNotice()
    assert notice.begin() is True
    assert notice.begin() is False
    assert notice.complete(AVAILABLE) == {'version': '0.3.0', 'notes': AVAILABLE['notes']}
    assert notice.begin() is False
    assert StartupNotice().begin() is True


@pytest.mark.parametrize('state', [None, {}, {'status': 'error'}, {'status': 'no_release'}, {'status': 'up_to_date'}, {'status': 'unconfigured'}, {'status': 'checking'}, {'status': 'downloaded'}, {'status': 'available', 'version': '../evil', 'notes': ''}, {'status': 'available', 'version': '1.2.3-beta', 'notes': ''}, {'status': 'available', 'version': '1.2.3', 'notes': None}, {'status': 'available', 'version': '1.2.3', 'notes': 'x'*4001}])
def test_only_valid_available_results_create_notice(state):
    notice = StartupNotice()
    notice.begin()
    assert notice.complete(state) is None
    assert notice.begin() is False


def test_completion_requires_pending_startup_and_is_consumed_once():
    notice = StartupNotice()
    assert notice.complete(AVAILABLE) is None
    assert notice.begin()
    assert notice.complete(AVAILABLE)
    assert notice.complete(AVAILABLE) is None


def test_dismissal_does_not_change_manual_update_state():
    manual = dict(AVAILABLE)
    notice = StartupNotice()
    notice.begin()
    assert notice.complete(manual)
    notice.dismiss()
    assert manual == AVAILABLE
    assert notice.complete(manual) is None


def test_dismissal_suppresses_late_pending_completion():
    notice = StartupNotice()
    notice.begin()
    notice.dismiss()
    assert notice.complete(AVAILABLE) is None


@pytest.mark.parametrize('method', ['close', 'cancel'])
def test_shutdown_invalidates_callbacks(method):
    notice = StartupNotice()
    notice.begin()
    getattr(notice, method)()
    assert notice.complete(AVAILABLE) is None
    assert notice.begin() is False


def test_result_is_detached_from_caller_state():
    notice = StartupNotice()
    notice.begin()
    state = dict(AVAILABLE)
    banner = notice.complete(state)
    state['notes'] = 'changed'
    assert banner['notes'] == AVAILABLE['notes']

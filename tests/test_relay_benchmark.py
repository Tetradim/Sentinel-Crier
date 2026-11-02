import asyncio
import json
import pytest

from scripts.benchmark_relay import run_benchmark, summarize


@pytest.mark.parametrize('reject_at',[1,7,41])
def test_receive_gate_probe_tolerates_one_window_boundary_and_stops_at_rejection(reject_at):
    from scripts.benchmark_relay import receive_limit_gate
    from types import SimpleNamespace
    class Client:
        calls=0
        async def post(self,path,**kwargs):
            self.calls+=1
            assert path=='/api/connect/receive' and kwargs=={'json':{'code':'!'}}
            return SimpleNamespace(status_code=429 if self.calls==reject_at else 422)
    client=Client()
    assert asyncio.run(receive_limit_gate(client))==429
    assert client.calls==reject_at


def test_receive_gate_probe_is_bounded_and_does_not_hide_missing_rate_limit():
    from scripts.benchmark_relay import receive_limit_gate
    from types import SimpleNamespace
    class Client:
        calls=0
        async def post(self,*args,**kwargs):
            self.calls+=1; return SimpleNamespace(status_code=422)
    client=Client()
    assert asyncio.run(receive_limit_gate(client))==422
    assert client.calls==41


def test_real_http_benchmark_preserves_deliveries_across_restart(tmp_path, monkeypatch):
    # Exercise the actual HTTP gate inside one controlled pairing window. Slow
    # hosted disks can otherwise spread 41 sequential requests over 3+ minutes,
    # correctly resetting the production gate before this probe reaches 20.
    # Replace only this module binding: delivery timestamps/latency clocks stay real.
    from types import SimpleNamespace
    from crier import quick_connect
    instant = quick_connect.time.time()
    monkeypatch.setattr(quick_connect, 'time', SimpleNamespace(time=lambda: instant))
    result = asyncio.run(run_benchmark(tmp_path, hosts=2, followers=2, events=4))
    assert result['expected_deliveries'] == 16
    assert result['successful_deliveries'] == 16
    assert result['failures'] == []
    assert result['recovery']['restart_cursor_preserved']
    assert result['recovery']['replay_preserved']
    assert result['recovery']['duplicate_publish_preserved']
    assert result['recovery']['independent_revocation']
    assert result['gates'] == {'missing_auth': 401, 'wrong_role': 401, 'malformed_event': 422, 'malformed_invitation': 422, 'receive_rate_limit': 429}
    assert result['transport_latency_ms']['count'] == 16
    assert result['queue_age_ms']['count'] == 16
    assert result['transport_latency_ms']['max'] >= result['transport_latency_ms']['p99'] >= 0
    assert 'Bearer' not in json.dumps(result)
    assert 'token' not in json.dumps(result)


def test_summary_uses_nearest_rank_and_empty_samples():
    assert summarize([]) == {'count': 0, 'p50': None, 'p95': None, 'p99': None, 'max': None}
    assert summarize([4, 1, 3, 2]) == {'count': 4, 'p50': 2, 'p95': 4, 'p99': 4, 'max': 4}


def test_invalid_load_and_reusing_data_are_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match='at least two events'):
        asyncio.run(run_benchmark(tmp_path, events=1))
    (tmp_path / 'intent-relay.sqlite3').touch()
    with pytest.raises(ValueError, match='fresh data directory'):
        asyncio.run(run_benchmark(tmp_path))


def test_cli_failure_is_redacted_and_nonzero(tmp_path):
    import subprocess
    import sys
    output = tmp_path / 'result.json'
    process = subprocess.run([sys.executable, '-m', 'scripts.benchmark_relay', '--events', '1', '--output', str(output)], capture_output=True, text=True)
    assert process.returncode == 1
    assert json.loads(output.read_text()) == {'failures': ['benchmark_aborted'], 'error_type': 'ValueError'}
    assert json.loads(process.stdout) == json.loads(output.read_text())
    assert process.stderr == ''


def test_real_receive_limiter_can_legitimately_reset_for_each_slow_request(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from crier import quick_connect
    from crier.intent_relay import IntentRelay
    from scripts.benchmark_relay import receive_limit_gate
    wall=[1000000]
    def advance():
        wall[0]+=60
        return wall[0]
    monkeypatch.setattr(quick_connect,'time',SimpleNamespace(time=advance))
    service=quick_connect.ConnectionService(IntentRelay(tmp_path/'slow-relay.sqlite3'))
    class Client:
        async def post(self,path,**kwargs):
            try:
                service.limit('receive','same-source',20,60)
                return SimpleNamespace(status_code=422)
            except ValueError:
                return SimpleNamespace(status_code=429)
    assert asyncio.run(receive_limit_gate(Client()))==422

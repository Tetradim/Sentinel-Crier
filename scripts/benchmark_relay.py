"""Broker-free HTTP/ASGI relay load and recovery exercise; emits aggregate data only.

Run from repository root: python -m scripts.benchmark_relay --help
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import platform
import secrets
import sys
import tempfile
import time
from uuid import NAMESPACE_URL, uuid5

import httpx

from crier.config import Config
from crier.connection_server import create_connection_app


class BenchmarkFailure(RuntimeError):
    """Only fixed, non-sensitive messages may reach benchmark output."""


def summarize(values):
    ordered = sorted(values)
    return {'count': len(ordered), **{
        name: ordered[max(0, math.ceil(len(ordered) * percentile) - 1)] if ordered else None
        for name, percentile in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]
    }}


def synthetic_event(host, index):
    now = datetime.now(timezone.utc)
    return dict(version=1, event_id=str(uuid5(NAMESPACE_URL, f'benchmark/{host}/{index}')),
                trade_id=str(uuid5(NAMESPACE_URL, f'benchmark/trade/{host}/{index}')),
                sequence=1, action='enter', environment='paper', symbol='SPY', asset='stock',
                quantity=1, limit_price='1.00', created_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=30)).isoformat())


def authorization(value):
    return {'Authorization': 'Bearer ' + value}


async def checked(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code != 200:
        raise BenchmarkFailure(f'HTTP {response.status_code} during benchmark request')
    return response.json()


async def run_benchmark(data_dir, *, hosts=1, followers=10, events=50, timeout=60):
    """followers and events are per host; each run requires an empty directory."""
    if min(hosts, followers) < 1 or events < 2 or timeout <= 0:
        raise ValueError('Require positive hosts/followers/timeout and at least two events')
    data_dir = Path(data_dir)
    if (data_dir / 'intent-relay.sqlite3').exists():
        raise ValueError('Benchmark requires a fresh data directory')
    config = Config(data_dir=data_dir, token=secrets.token_urlsafe(32), public_pairing_enabled=True)
    pairs = []
    failures = []
    latency, queue_age = [], []
    published = {}
    cursors = {}
    received = set()
    recovery = dict(restart_cursor_preserved=True, replay_preserved=True,
                    duplicate_publish_preserved=True, independent_revocation=True)
    gates = {}

    async def client_for(stack, app, address):
        return await stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(address, 12345)),
            base_url='http://benchmark.invalid'))

    async def exercise_phase(clients, start, stop):
        async def publish(host_index, host_client):
            for index in range(start, stop):
                value = synthetic_event(host_index, index)
                published[(host_index, index)] = (value, time.perf_counter())
                result = await checked(host_client, 'POST', '/api/sync/events',
                                       headers=authorization(pairs[host_index]['host']), json=value)
                published[(host_index, index)] += (result['cursor'],)
                await asyncio.sleep(0)

        async def follow(host_index, follower_index, client):
            key = (host_index, follower_index)
            wanted = stop - start
            count = 0
            while count < wanted:
                result = await checked(client, 'GET', '/api/sync/events',
                                       headers=authorization(pairs[host_index]['followers'][follower_index]),
                                       params={'after': cursors.get(key, 0), 'wait': 1})
                for row in result['events']:
                    stamp = time.perf_counter()
                    value = row['event']
                    index = next((n for n in range(start, stop)
                                  if published.get((host_index, n), ({},))[0].get('event_id') == value['event_id']), None)
                    if index is None or (host_index, follower_index, index) in received:
                        raise BenchmarkFailure('Unexpected or duplicate delivery')
                    original, sent, *_ = published[(host_index, index)]
                    # The protocol normalizes timestamp/decimal strings; compare parsed times separately.
                    if any(value[k] != original[k] for k in original if k not in ('created_at', 'expires_at')):
                        raise BenchmarkFailure('Delivery content mismatch')
                    now = datetime.now(timezone.utc)
                    created = datetime.fromisoformat(value['created_at'].replace('Z', '+00:00'))
                    expires = datetime.fromisoformat(value['expires_at'].replace('Z', '+00:00'))
                    if now >= expires:
                        failures.append('event_expired_before_receipt')
                    latency.append((stamp - sent) * 1000)
                    queue_age.append((now - created).total_seconds() * 1000)
                    received.add((host_index, follower_index, index))
                    count += 1
                cursors[key] = result['cursor']

        tasks = [follow(h, f, clients[h][1][f]) for h in range(hosts) for f in range(followers)]
        # Let readers enter long polling before the publishers start.
        running = [asyncio.create_task(task) for task in tasks]
        await asyncio.sleep(.02)
        running.extend(asyncio.create_task(publish(h, clients[h][0])) for h in range(hosts))
        try:
            await asyncio.wait_for(asyncio.gather(*running), timeout)
        finally:
            for task in running:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*running, return_exceptions=True)

    started = time.perf_counter()
    load_seconds = 0
    for phase, (start, stop) in enumerate([(0, events // 2), (events // 2, events)]):
        app = create_connection_app(config)
        async with app.router.lifespan_context(app), AsyncExitStack() as stack:
            clients = []
            for h in range(hosts):
                host_client = await client_for(stack, app, f'host-{h}')
                follower_clients = [await client_for(stack, app, f'follower-{h}-{f}') for f in range(followers)]
                clients.append((host_client, follower_clients))
                if phase == 0:
                    pair = await checked(host_client, 'POST', '/api/connect/host', json={'name': f'Benchmark {h}', 'environment': 'paper'})
                    pair = {'host': pair['token'], 'followers': []}
                    pairs.append(pair)
                    # A fresh source for each invitation models independent pairing clients and
                    # respects the public per-source invitation gate for large declared loads.
                    for f, client in enumerate(follower_clients):
                        invite_client = await client_for(stack, app, f'invite-{h}-{f}')
                        invite = await checked(invite_client, 'POST', '/api/connect/invite', headers=authorization(pair['host']))
                        follower = await checked(client, 'POST', '/api/connect/receive', json={'code': invite['code'], 'environment': 'paper'})
                        pair['followers'].append(follower['token'])
                    if len(set(pair['followers'])) != followers:
                        raise BenchmarkFailure('Receivers did not obtain independent credentials')
                else:
                    for f, client in enumerate(follower_clients):
                        replay = await checked(client, 'GET', '/api/sync/events', headers=authorization(pairs[h]['followers'][f]), params={'after': 0, 'wait': 0})
                        # Pagination is part of the transport contract (500 events/page).
                        replay_ids = [row['event']['event_id'] for row in replay['events']]
                        after = replay['cursor']
                        while len(replay_ids) < start:
                            page = await checked(client, 'GET', '/api/sync/events', headers=authorization(pairs[h]['followers'][f]), params={'after': after, 'wait': 0})
                            if not page['events']:
                                break
                            replay_ids.extend(row['event']['event_id'] for row in page['events'])
                            after = page['cursor']
                        recovery['replay_preserved'] &= replay_ids == [published[(h, n)][0]['event_id'] for n in range(start)]
                        empty = await checked(client, 'GET', '/api/sync/events', headers=authorization(pairs[h]['followers'][f]), params={'after': cursors[(h, f)], 'wait': 0})
                        recovery['restart_cursor_preserved'] &= not empty['events'] and empty['cursor'] == cursors[(h, f)]
                    value, _, cursor = published[(h, 0)]
                    duplicate = await checked(host_client, 'POST', '/api/sync/events', headers=authorization(pairs[h]['host']), json=value)
                    recovery['duplicate_publish_preserved'] &= duplicate['cursor'] == cursor
            phase_started = time.perf_counter()
            await exercise_phase(clients, start, stop)
            load_seconds += time.perf_counter() - phase_started
            if phase == 1:
                client = clients[0][0]
                follower = pairs[0]['followers'][0]
                gates['missing_auth'] = (await client.get('/api/sync/events', params={'wait': 0})).status_code
                gates['wrong_role'] = (await client.get('/api/sync/events', headers=authorization(pairs[0]['host']), params={'wait': 0})).status_code
                gates['malformed_event'] = (await client.post('/api/sync/events', headers=authorization(pairs[0]['host']), json={})).status_code
                bad_client = await client_for(stack, app, 'malformed-receive')
                gates['malformed_invitation'] = (await bad_client.post('/api/connect/receive', json={'code': '!'})).status_code
                for _ in range(20):
                    rate_response = await bad_client.post('/api/connect/receive', json={'code': '!'})
                gates['receive_rate_limit'] = rate_response.status_code
                receivers = await checked(client, 'GET', '/api/connect/receivers', headers=authorization(pairs[0]['host']))
                await checked(client, 'POST', '/api/connect/receivers/' + receivers[0]['id'] + '/revoke', headers=authorization(pairs[0]['host']))
                rejected = await client.get('/api/sync/events', headers=authorization(follower), params={'wait': 0})
                recovery['independent_revocation'] = rejected.status_code == 401
                for other in pairs[0]['followers'][1:]:
                    response = await client.get('/api/sync/events', headers=authorization(other), params={'wait': 0})
                    recovery['independent_revocation'] &= response.status_code == 200
    expected_gates = dict(missing_auth=401, wrong_role=401, malformed_event=422, malformed_invitation=422, receive_rate_limit=429)
    failures.extend('recovery_' + key for key, okay in recovery.items() if not okay)
    failures.extend('gate_' + key for key, expected in expected_gates.items() if gates.get(key) != expected)
    return dict(schema_version=1, transport='httpx.ASGITransport (in-process; no network or broker)',
                environment={'python': platform.python_version(), 'platform': platform.platform(), 'httpx': httpx.__version__},
                load={'hosts': hosts, 'followers_per_host': followers, 'events_per_host': events},
                expected_deliveries=hosts * followers * events, successful_deliveries=len(received), failures=failures,
                transport_latency_ms=summarize(latency), queue_age_ms=summarize(queue_age),
                load_duration_seconds=load_seconds, duration_seconds=time.perf_counter() - started,
                deliveries_per_second=len(received) / load_seconds, recovery=recovery, gates=gates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hosts', type=int, default=1)
    parser.add_argument('--followers', type=int, default=10, help='Followers per host')
    parser.add_argument('--events', type=int, default=50, help='Events per host, at least two')
    parser.add_argument('--timeout', type=float, default=60, help='Seconds allowed per load phase')
    parser.add_argument('--output', type=Path, help='Optional aggregate JSON output; contains no credentials or event content')
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='crier-relay-benchmark-') as directory:
            result = asyncio.run(run_benchmark(directory, hosts=args.hosts, followers=args.followers, events=args.events, timeout=args.timeout))
    except Exception as exc:
        # Exception text may contain request data. Emit only a controlled type name.
        result = {'failures': ['benchmark_aborted'], 'error_type': type(exc).__name__}
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 1 if result['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())

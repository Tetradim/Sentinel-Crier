"""Private relay readiness and bounded, credential-free operational metrics."""
from collections import defaultdict
from dataclasses import dataclass
import math
import os
import shutil
import tempfile
from threading import Lock
import time


# Explicit required columns detect partial/old schemas without reading event contents.
REQUIRED_SCHEMA = {
    'channels': 'id,name,environment,host_digest,follower_digest,revoked',
    'receivers': 'id,channel,token_digest,created,revoked,start_cursor',
    'intents': 'cursor,channel,event_id,trade_id,sequence,identity,payload',
    'diagnostics': 'channel,event_id,actor,observation',
    'invitations': 'code_digest,channel,expires',
    'connection_limits': 'id,window,count',
}


@dataclass(frozen=True)
class OpsSettings:
    min_free_bytes: int = 64 * 1024 * 1024
    min_free_percent: float = 1.0

    def __post_init__(self):
        if self.min_free_bytes < 0 or not math.isfinite(self.min_free_percent) or not 0 <= self.min_free_percent <= 100:
            raise ValueError('Invalid relay free disk thresholds')

    @classmethod
    def from_env(cls):
        return cls(int(os.getenv('CRIER_RELAY_MIN_FREE_BYTES', str(64 * 1024 * 1024))),
                   float(os.getenv('CRIER_RELAY_MIN_FREE_PERCENT', '1')))


class RelayOperations:
    def __init__(self, relay, settings=None):
        self.relay = relay
        self.settings = settings or OpsSettings.from_env()
        self.started = time.monotonic()
        self.lock = Lock()
        self.requests = defaultdict(lambda: {'count': 0, 'latency_seconds_sum': 0.0, 'latency_seconds_max': 0.0})
        self.jobs = {}
        self.probe_lock = Lock()
        self.public_probe = (0.0, False)

    def public_ready(self):
        checked, ready = self.public_probe
        if time.monotonic() - checked < 2:
            return ready
        if not self.probe_lock.acquire(blocking=False):
            return ready
        try:
            checked, ready = self.public_probe
            if time.monotonic() - checked >= 2:
                ready = self.readiness()['ready']
                self.public_probe = (time.monotonic(), ready)
            return ready
        finally:
            self.probe_lock.release()

    def record_job(self, name, success):
        # Only fixed operational job names; callers cannot introduce identity labels.
        if name not in ('health', 'backup', 'retention'):
            raise ValueError('Unknown operations job')
        with self.lock:
            self.jobs[name] = {'success': bool(success), 'completed_at': time.time()}

    def record_request(self, route, method, status, elapsed):
        method = method if method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS') else 'OTHER'
        with self.lock:
            item = self.requests[(route, method, int(status))]
            item['count'] += 1
            item['latency_seconds_sum'] += elapsed
            item['latency_seconds_max'] = max(item['latency_seconds_max'], elapsed)

    def readiness(self, include_counts=False):
        result = {'ready': True, 'database': {'ready': False}, 'disk': {'ready': False}}
        try:
            with self.relay.db() as db:
                db.execute('PRAGMA busy_timeout=100')
                for table, columns in REQUIRED_SCHEMA.items():
                    db.execute(f'SELECT {columns} FROM {table} LIMIT 0')
                # Acquire the write lock too: a relay unable to accept writes is unready.
                db.execute('BEGIN IMMEDIATE')
                if include_counts:
                    result['counts'] = {name: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                                        for name, table in (('channels', 'channels'), ('receivers', 'receivers'), ('events', 'intents'))}
                db.rollback()
            result['database']['ready'] = True
        except Exception:
            # Never return SQL, filesystem paths, or exception text to clients.
            result['ready'] = False
        try:
            usage = shutil.disk_usage(self.relay.path.parent)
            free_percent = 100 * usage.free / usage.total if usage.total else 0
            with tempfile.TemporaryFile(dir=self.relay.path.parent) as probe:
                probe.write(b'relay readiness\n')
                probe.flush()
                os.fsync(probe.fileno())
            enough = usage.free >= self.settings.min_free_bytes and free_percent >= self.settings.min_free_percent
            result['disk'] = {'ready': enough, 'total_bytes': usage.total, 'used_bytes': usage.used,
                              'free_bytes': usage.free, 'free_percent': round(free_percent, 2),
                              'min_free_bytes': self.settings.min_free_bytes,
                              'min_free_percent': self.settings.min_free_percent}
            if not enough:
                result['ready'] = False
        except Exception:
            result['ready'] = False
        return result

    def snapshot(self):
        result = self.readiness(include_counts=True)
        result['uptime_seconds'] = round(time.monotonic() - self.started, 3)
        with self.lock:
            result['requests'] = [{'route': route, 'method': method, 'status': status, **values}
                                  for (route, method, status), values in sorted(self.requests.items())]
            result['jobs'] = {name: dict(value) for name, value in self.jobs.items()}
        return result


class RequestMetrics:
    """ASGI boundary includes body rejection and exceptions; stores no URL or headers."""
    def __init__(self, app, operations, routes):
        self.app, self.operations, self.routes = app, operations, routes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started, status = time.monotonic(), 500

        async def measured_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            matched = getattr(scope.get('route'), 'path', None)
            # Unmatched paths, query strings, identities, and secrets never become labels.
            route = matched if matched in self.routes else 'unmatched'
            self.operations.record_request(route, scope['method'], status, time.monotonic() - started)

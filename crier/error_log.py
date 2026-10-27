"""Bounded, nonblocking technical evidence. Never format exception messages.

Execution journals remain authoritative. A full/broken logger drops evidence,
reports that loss, and never authorizes or retries a broker operation.
"""
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import queue
import re
import threading
import time
import traceback
from uuid import UUID
import zipfile


def read_build_info(path):
    """Public build resource only; never inspect user configuration or Git at runtime."""
    try:
        with Path(path).open('rb') as stream: raw = stream.read(2049)
        if len(raw)>2048: return None
        value=json.loads(raw.decode('utf-8-sig'))
        if (not isinstance(value,dict) or set(value)!= {'schema','version','commit'} or value['schema']!=1
                or not isinstance(value['version'],str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',value['version'])
                or not isinstance(value['commit'],str) or not re.fullmatch(r'[a-f0-9]{40}|unknown',value['commit'])): return None
        return value
    except (OSError,ValueError,UnicodeError): return None


def _uuid(value):
    try: return value if isinstance(value, str) and str(UUID(value)) == value else None
    except (ValueError, TypeError, AttributeError): return None


def _context(values):
    result = {}
    if value := _uuid(values.get('trade_id')): result['trade_id'] = value
    if values.get('environment') in ('paper', 'live'): result['environment'] = values['environment']
    cid = values.get('client_order_id')
    if isinstance(cid, str):
        match = re.fullmatch(r'si-([a-f0-9-]{36})-(?:b|s[0-9]{1,5})', cid)
        if match and _uuid(match[1]): result['client_order_id'] = cid
    return result


def _safe(record):
    """Validate again on export; arbitrary JSON/fields must not become attachments."""
    if not isinstance(record, dict) or record.get('schema') != 1: return None
    code = record.get('code'); stamp = record.get('timestamp')
    if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,119}', code): return None
    if record.get('level') not in ('ERROR', 'EVENT') or not isinstance(stamp, str): return None
    try:
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None: return None
    except ValueError: return None
    result = dict(schema=1, timestamp=stamp, code=code, level=record['level'], **_context(record))
    error_type = record.get('exception_type')
    if isinstance(error_type, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,99}', error_type): result['exception_type'] = error_type
    stack = []
    for frame in record.get('stack', [])[:12] if isinstance(record.get('stack'), list) else []:
        if not isinstance(frame, dict): continue
        file, function, line = frame.get('file'), frame.get('function'), frame.get('line')
        if (isinstance(file, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', file)
                and isinstance(function, str) and re.fullmatch(r'[A-Za-z0-9_<>.]{1,120}', function)
                and isinstance(line, int) and not isinstance(line, bool) and 0 < line < 10000000):
            stack.append(dict(file=file, function=function, line=line))
    if stack: result['stack'] = stack
    return result


class ErrorLog:
    def __init__(self, folder, *, max_bytes=2*1024*1024, backups=3, capacity=512):
        if max_bytes < 256 or not 0 <= backups <= 8 or capacity < 1: raise ValueError('Invalid diagnostic bounds')
        self.folder = Path(folder).resolve(); self.max_bytes = max_bytes; self.backups = backups
        self.queue = queue.Queue(maxsize=capacity); self.closing = threading.Event()
        self.failed = False; self.dropped = 0; self.suppressed = 0
        self._cache = {}; self._lock = threading.Lock(); self._thread = None; self._handler = None
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            owner = self
            class QuietHandler(RotatingFileHandler):
                def handleError(self, record): owner.failed = True
            self._handler = QuietHandler(self.folder/'error-log.jsonl', maxBytes=max_bytes, backupCount=backups, encoding='utf-8', delay=True)
            self._thread = threading.Thread(target=self._run, name='crier-error-log', daemon=True)
            self._thread.start()
        except OSError: self.failed = True

    def status(self):
        return dict(available=not self.failed and bool(self._thread and self._thread.is_alive()) and not self.closing.is_set(), queued=self.queue.qsize(), dropped=self.dropped, suppressed=self.suppressed)

    def _emit(self, record):
        if self.failed or self.closing.is_set(): return False
        value = _safe(record)
        if value is None: return False
        try: self.queue.put_nowait(value); return True
        except queue.Full: self.dropped += 1; return False

    def event(self, code, **context):
        return self._emit(dict(schema=1, timestamp=datetime.now(timezone.utc).isoformat(), level='EVENT', code=code, **_context(context)))

    def error(self, code, error, **context):
        # Never call str/repr(error), traceback.format_exception or capture_locals.
        kind = type(error).__name__; key = (code, kind, _uuid(context.get('trade_id')))
        if not self._lock.acquire(blocking=False): self.dropped += 1; return False
        try:
            now = time.monotonic()
            if now-self._cache.get(key, float('-inf')) < 30: self.suppressed += 1; return False
            if len(self._cache) >= 256: self._cache.pop(next(iter(self._cache)))
            self._cache[key] = now
        finally: self._lock.release()
        frames = traceback.extract_tb(error.__traceback__, limit=12) if isinstance(error, BaseException) else []
        return self._emit(dict(schema=1, timestamp=datetime.now(timezone.utc).isoformat(), level='ERROR', code=code,
                               exception_type=kind, stack=[dict(file=Path(f.filename).name, function=f.name, line=f.lineno) for f in frames], **_context(context)))

    def _write(self, record):
        message = json.dumps(record, separators=(',', ':'), ensure_ascii=True)
        self._handler.emit(logging.LogRecord('crier.technical', logging.INFO, '', 0, message, (), None))

    def _run(self):
        try:
            while not self.closing.is_set() or not self.queue.empty():
                try: item = self.queue.get(timeout=0.1)
                except queue.Empty: continue
                try:
                    if isinstance(item, threading.Event):
                        try: self._handler.flush()
                        finally: item.set()
                    else: self._write(item)
                except Exception: self.failed = True
                finally: self.queue.task_done()
        finally:
            try: self._handler.close()
            except Exception: self.failed = True

    def flush(self, timeout=2):
        if self.failed or not self._thread or not self._thread.is_alive(): return False
        done = threading.Event()
        try: self.queue.put_nowait(done)
        except queue.Full: return False
        return done.wait(timeout) and not self.failed

    def close(self):
        self.closing.set()
        if self._thread: self._thread.join(timeout=2)
        return not self._thread or not self._thread.is_alive()

    def export(self, target):
        target = Path(target)
        if target.exists(): raise FileExistsError('Choose a new support archive filename')
        if target.suffix.lower() != '.zip': raise ValueError('Support archive must be ZIP')
        if not self.flush(): raise RuntimeError('Diagnostic writer unavailable or still busy; retry export later')
        try: app_version = version('sentinel-crier')
        except PackageNotFoundError: app_version = 'unknown'
        records = []; skipped = 0
        for suffix in reversed([''] + ['.'+str(n) for n in range(1,self.backups+1)]):
            path = self.folder/('error-log.jsonl'+suffix)
            if not path.exists(): continue
            if path.is_symlink() or path.resolve().parent != self.folder: skipped += 1; continue
            try:
                with path.open('rb') as stream: data = stream.read(self.max_bytes+8192)
            except OSError:
                skipped += 1; continue  # Rotation/storage may race this best-effort snapshot.
            for line in data.splitlines():
                try: record = _safe(json.loads(line))
                except (ValueError, UnicodeError): record = None
                if record is None: skipped += 1
                else: records.append(record)
        manifest = dict(schema=1, application='Sentinel Crier', version=app_version, platform=platform.system(),
                        python=platform.python_version(), exported_at=datetime.now(timezone.utc).isoformat(),
                        logging=self.status(), skipped_records=skipped, includes_credentials=False,
                        includes_raw_databases=False, includes_exception_messages=False)
        build=read_build_info(Path(__file__).with_name('build-info.json'))
        if build: manifest['build']=build;manifest['version']=build['version']
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, indent=2))
            archive.writestr('diagnostics/error-log.jsonl', ''.join(json.dumps(row)+'\n' for row in records))
        return str(target)


def emit_error(sink, code, error, **context):
    try:
        if sink is not None: return sink.error(code, error, **context)
    except Exception: pass
    return False


def emit_event(sink, code, **context):
    try:
        if sink is not None: return sink.event(code, **context)
    except Exception: pass
    return False

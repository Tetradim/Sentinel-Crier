"""Own a read-only observer child process for the single-command application."""
import json
import multiprocessing
import time

from .store import Store
from .lock import AlreadyRunningError


def run_monitor(config):
    try:
        if config.monitor == "webull":
            from .webull import observe
        elif config.monitor == "tradier":
            from .tradier import observe
        elif config.monitor == "alpaca":
            from .alpaca import observe
        else:
            return
        observe(config)
    except AlreadyRunningError:
        # Do not overwrite the healthy observer that already owns this store.
        Store(config.data_dir / "crier.sqlite3").audit("monitor_start_blocked", {"reason": "Observer already running"})
        raise SystemExit(1) from None
    except Exception:
        # Broker exception strings can include credentials or raw account data.
        with Store(config.data_dir / "crier.sqlite3").connect() as db:
            db.execute("INSERT OR REPLACE INTO config VALUES ('observer',?)",
                       (json.dumps({"state": "error", "updated": time.time(), "broker": config.monitor,
                                    "reason": "Monitor stopped; check configuration and private validation guide"}),))
        raise SystemExit(1) from None


def start_monitor(config):
    if config.monitor == "none":
        return None
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=run_monitor, args=(config,), name="crier-monitor", daemon=True)
    process.start()
    return process


def stop_monitor(process):
    if process is not None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)

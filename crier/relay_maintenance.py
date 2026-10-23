"""Single-worker periodic backup scheduling; no broker or notification clients."""
import asyncio
import os
from pathlib import Path


def backup_options(data_dir):
    interval=int(os.getenv('CRIER_BACKUP_INTERVAL_SECONDS','86400'))
    retention=int(os.getenv('CRIER_BACKUP_RETAIN','7'))
    if interval<60 or not 1<=retention<=365:
        raise ValueError('Backup interval must be at least 60 seconds; retention must be 1..365')
    destination=Path(os.getenv('CRIER_BACKUP_DIR',str(Path(data_dir)/'backups')))
    return destination,interval,retention


async def backup_loop(data_dir, destination, interval, retention, stop, operations, create):
    while not stop.is_set():
        try:
            await asyncio.to_thread(create,data_dir,destination,retain=retention)
            operations.record_job('backup',True)
        except Exception:
            # No exception text: paths/DB contents may contain private data.
            operations.record_job('backup',False)
        try:
            await asyncio.wait_for(stop.wait(),timeout=interval)
        except asyncio.TimeoutError:
            pass

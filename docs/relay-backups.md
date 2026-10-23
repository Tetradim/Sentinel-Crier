# Relay backups and offline restore

The relay writes `intent-relay.sqlite3` in `CRIER_DATA_DIR` (default `data`).
Use SQLite's online backup API, never a filesystem copy of the live database.
Committed changes can be in the `-wal` file, and copying the database and WAL
separately does not produce a consistent snapshot. Online backups may run while
the relay accepts events. They capture a consistent committed database state.

A snapshot contains channel credentials/digests, invitation digests, receiver
credentials/digests, events, diagnostics, and connection limits. Treat it as a
secret. This tool restricts the backup directory to its owner: mode 0700 on
POSIX, and a protected owner-only ACL on Windows. Snapshot files use mode 0600
on POSIX and inherit the private directory ACL on Windows. Use a dedicated
backup directory owned by the relay account. Restrict its parent directory too;
other users must not be able to replace directory entries. Symlink and junction
paths are refused. Snapshots are not encrypted: use encrypted, access-controlled
storage and protect any off-machine copies with equivalent permissions.

```sh
python -m crier.relay_backup backup --data-dir data --backup-dir relay-backups --retain 7
python -m crier.relay_backup verify relay-backups/relay-YYYYMMDDTHHMMSSffffffZ-ID
```

Each snapshot is a directory containing exactly `intent-relay.sqlite3` and
`manifest.json`. The manifest contains format version, fixed database filename,
UTC creation time, byte count, and SHA-256 checksum; it contains no tokens or
payloads. SQLite integrity and relay schema checks run before publication and
again during verification. SHA-256 detects accidental corruption, not a
malicious replacement by someone who can rewrite both files.

Creation uses a private staging directory, flushes files, and renames the whole
directory atomically on the same filesystem. Interrupted `.pending-*` directories
are not valid snapshots and may be removed while no backup process is running.
Retention keeps the newest configured number of complete snapshots (default 7).
Only directories with the tool's exact snapshot naming pattern and verified
contents qualify for deletion. Unknown entries are left alone; an invalid named
snapshot makes pruning fail conservatively. A newly published valid snapshot may
remain even if subsequent pruning fails. A backup-directory lock serializes
backup/pruning operations. Keep an off-machine copy: snapshots on the same disk
cannot protect against loss of that disk. Test restore periodically.

## Restore

Stop every relay service/process using the data directory. Restore takes the
same `connection-server.lock` as the service and refuses a live service. Do not
start the service until restore finishes. Other programs must not bypass that
lock to access the database during restore.

Prefer restoring into a new empty directory first:

```sh
python -m crier.relay_backup restore relay-backups/relay-YYYYMMDDTHHMMSSffffffZ-ID --data-dir recovered-data
```

Existing databases require the explicit `--overwrite` flag. Existing WAL, SHM,
or rollback-journal sidecars cause refusal, even with that flag; never delete
these files by hand. After stopping the service, checkpoint and close the old
database using SQLite before attempting overwrite. For example, run this from
the project directory, adjusting the data path:

```python
from contextlib import closing
import sqlite3
from crier.lock import single_process

with single_process('data/connection-server.lock'):
    with closing(sqlite3.connect('data/intent-relay.sqlite3')) as db:
        result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result[0]:
            raise RuntimeError('Another SQLite connection is still active')
        db.execute('PRAGMA journal_mode=DELETE').fetchone()
```

```sh
python -m crier.relay_backup restore relay-backups/relay-YYYYMMDDTHHMMSSffffffZ-ID --data-dir data --overwrite
```

Restore validates the snapshot and stages a new private database before an
atomic replacement. Invalid snapshots and staging failures leave the existing
database untouched. A temporary hard link preserves the old database for
rollback if directory sync fails after replacement. Restore only targets the
fixed relay filename; it cannot restore arbitrary filenames from a manifest.
It never deletes live SQLite sidecars. The relay re-enables WAL on next startup.

The snapshot does **not** include deployment environment variables, certificates,
service definitions, or an `access-token` file. Securely preserve the owner
`CRIER_ACCESS_TOKEN` / data-directory `access-token` separately, together with
any environment configuration needed to restart the service. Do not print them
in logs or put them in this manifest. Restoring an older database also restores
its earlier invitation/credential/revocation state, so review device access and
revoke credentials as needed before exposing the recovered relay. Events after
the snapshot are absent. Reconcile devices against the recovered state before
resuming use.

The module also provides `create_backup(data_dir, backup_dir, retain=7)`,
`verify_backup(snapshot)`, and `restore_backup(snapshot, data_dir, overwrite=False)`
for local scheduling. The first and last return their resulting paths.

#!/usr/bin/env python3
"""Interactively re-encrypt the Android private signing key for portable custody."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def certificate_fingerprint(output):
    matches = re.findall(r"SHA256:\s*([0-9a-fA-F:]+)", output)
    pins = {value.replace(":", "").lower() for value in matches}
    if len(pins) != 1 or not re.fullmatch(r"[0-9a-f]{64}", next(iter(pins), "")):
        raise ValueError("Expected one SHA-256 signing certificate")
    return pins.pop()


def _run(keytool, args, environment, runner):
    try:
        result = runner([keytool, "-J-Duser.language=en", "-J-Duser.country=US", *args],
                        env=environment, capture_output=True, text=True,
                        stdin=subprocess.DEVNULL, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("keytool could not complete; no subprocess output is disclosed") from None
    if result.returncode:
        raise ValueError("keytool verification/export failed; no subprocess output is disclosed")
    return result.stdout


def _inspect(keytool, keystore, alias, password_env, environment, runner):
    output = _run(keytool, ["-list", "-v", "-storetype", "PKCS12", "-keystore", str(keystore),
                           "-alias", alias, "-storepass:env", password_env], environment, runner)
    if "Entry type: PrivateKeyEntry" not in output:
        raise ValueError("The signing alias must contain a private key")
    return certificate_fingerprint(output)


def export_backup(identity, destination, backup_password, source_password, alias,
                  *, keytool="keytool", runner=subprocess.run):
    """Export only to a newly created directory; never rewrite the source identity."""
    if not isinstance(backup_password, str) or len(backup_password) < 16 or any(c in backup_password for c in "\r\n\0"):
        raise ValueError("Use a backup passphrase of at least 16 characters without line breaks or NUL")
    if not source_password or not alias or any(c in source_password + alias for c in "\r\n\0"):
        raise ValueError("Invalid source signing credentials")
    identity, destination = Path(identity).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must be a new directory (existing directories are never reused)")
    source = identity / "android-release.p12"
    pin = (identity / "android-certificate-sha256.txt").read_text(encoding="utf-8").strip().replace(":", "").lower()
    if not source.is_file() or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("Source keystore or public certificate pin is missing or invalid")
    environment = dict(os.environ, CRIER_BACKUP_SOURCE_PASSWORD=source_password,
                       CRIER_BACKUP_DEST_PASSWORD=backup_password)
    if _inspect(keytool, source, alias, "CRIER_BACKUP_SOURCE_PASSWORD", environment, runner) != pin:
        raise ValueError("Source certificate does not match the public pin")
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError("Destination must be a new directory") from None
    created = []
    exported = destination / "android-release-backup.p12"
    try:
        # The newly created directory is exclusively this operation's output.
        created.append(exported)
        _run(keytool, ["-importkeystore", "-noprompt", "-srckeystore", str(source),
                       "-srcstoretype", "PKCS12", "-srcalias", alias,
                       "-srcstorepass:env", "CRIER_BACKUP_SOURCE_PASSWORD",
                       "-srckeypass:env", "CRIER_BACKUP_SOURCE_PASSWORD",
                       "-destkeystore", str(exported), "-deststoretype", "PKCS12", "-destalias", alias,
                       "-deststorepass:env", "CRIER_BACKUP_DEST_PASSWORD",
                       "-destkeypass:env", "CRIER_BACKUP_DEST_PASSWORD"], environment, runner)
        os.chmod(exported, 0o600)
        if _inspect(keytool, exported, alias, "CRIER_BACKUP_DEST_PASSWORD", environment, runner) != pin:
            raise ValueError("Reopened backup certificate does not match the public pin")
        manifest = {"format": "SentinelCrier Android signing backup v1", "store_type": "PKCS12",
                    "alias": alias, "certificate_sha256": pin,
                    "keystore_sha256": hashlib.sha256(exported.read_bytes()).hexdigest(),
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "keystore_file": exported.name}
        public_files = {
            "manifest.json": json.dumps(manifest, indent=2) + "\n",
            "SHA256SUMS.txt": manifest["keystore_sha256"] + "  " + exported.name + "\n",
            "RESTORE.txt": RESTORE_INSTRUCTIONS,
        }
        for name, content in public_files.items():
            path = destination / name
            with path.open("x", encoding="utf-8") as file:
                created.append(path)
                file.write(content)
        return manifest
    except BaseException:
        # No recursive deletion: a concurrent/unrelated file prevents rmdir and survives.
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            destination.rmdir()
        except OSError:
            pass
        raise
    finally:
        environment.pop("CRIER_BACKUP_SOURCE_PASSWORD", None)
        environment.pop("CRIER_BACKUP_DEST_PASSWORD", None)


RESTORE_INSTRUCTIONS = """SentinelCrier Android signing identity recovery

The PKCS12 file contains an encrypted private signing key. Keep its passphrase in
separate owner-controlled custody. The original Windows DPAPI secret is not needed.
1. On a trusted recovery computer with a JDK, compare the file's SHA-256 with
   SHA256SUMS.txt and a separately retained trusted copy of manifest.json.
2. Run: keytool -list -v -storetype PKCS12 -keystore android-release-backup.p12
   Enter the backup passphrase at keytool's password prompt. Verify the alias,
   PrivateKeyEntry type, and SHA256 certificate against the trusted manifest/pin.
3. In an isolated release signing environment configure this PKCS12, manifest alias,
   and the backup passphrase for BOTH store and key passwords. Use the existing
   protected signing-secret provisioning process; never paste credentials into logs,
   shell arguments, source files, tickets, or release notes.
4. Sign a disposable candidate and verify its certificate against the public pin
   before provisioning production CI or changing an existing signing installation.
   Never generate a replacement signing identity for an application update.
5. Retain the original identity until a separate-machine restore/signing drill and
   the offline copy's checksum verification have been recorded by the owner.

This manifest and checksum detect accidental corruption; independently retain the
trusted public fingerprint to detect replacement of the entire backup directory.
"""


def request_password(gui=False):
    if gui:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            password = simpledialog.askstring("SentinelCrier signing backup", "New offline backup passphrase (at least 16 characters):", show="*", parent=root)
            if password is None:
                raise ValueError("Backup cancelled")
            confirmation = simpledialog.askstring("SentinelCrier signing backup", "Confirm offline backup passphrase:", show="*", parent=root)
        finally:
            root.destroy()
    else:
        # Refuse getpass's fallback to visible terminal input.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("New offline backup passphrase (at least 16 characters): ")
            confirmation = getpass.getpass("Confirm offline backup passphrase: ")
    if confirmation is None or password != confirmation:
        raise ValueError("Passphrases do not match or backup cancelled")
    return password


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "SentinelCrier/Signing"
    parser.add_argument("--identity-dir", type=Path, default=default)
    parser.add_argument("--destination", type=Path, required=True, help="new directory on trusted owner-controlled storage")
    parser.add_argument("--keytool", default=shutil.which("keytool") or "keytool")
    parser.add_argument("--gui", action="store_true", help="use masked native password dialogs (also supports pythonw)")
    args = parser.parse_args(argv)
    if not args.gui and (sys.stdin is None or not sys.stdin.isatty()):
        parser.error("Run interactively in a trusted terminal; redirected password input is refused")
    try:
        password = request_password(args.gui)
        from crier.device_secrets import load_secret
        credentials = json.loads(load_secret(args.identity_dir / "android-signing.secret"))
        export_backup(args.identity_dir, args.destination, password, credentials["password"], credentials["alias"], keytool=args.keytool)
    except (ValueError, OSError, KeyError, TypeError, getpass.GetPassWarning):
        message = "Backup failed or was cancelled. Check the source identity, new destination, JDK, and passphrase. Secret details are suppressed."
        if args.gui:
            from tkinter import messagebox
            messagebox.showerror("SentinelCrier signing backup", message)
        else:
            print(message, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Backup cancelled.", file=sys.stderr)
        return 1
    message = "Verified encrypted backup created at " + str(args.destination) + ". Copy it offline, retain the passphrase separately, and complete a recovery drill."
    if args.gui:
        from tkinter import messagebox
        messagebox.showinfo("SentinelCrier signing backup", message)
    else:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

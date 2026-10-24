"""Backup safety tests; the integration case uses only a generated disposable key."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/android-signing-backup.py"


@pytest.fixture
def backup():
    assert SCRIPT.exists(), "Android signing backup helper must exist"
    spec = importlib.util.spec_from_file_location("android_backup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PIN = "ab" * 32


@pytest.fixture
def source(tmp_path):
    identity = tmp_path / "identity"
    identity.mkdir()
    (identity / "android-release.p12").write_bytes(b"source-keystore")
    (identity / "android-certificate-sha256.txt").write_text(PIN)
    return identity


def fake_runner(calls, *, wrong_pin=False, wrong_reopen=False, fail_import=False, certificate_only=False):
    def run(argv, **kwargs):
        calls.append((argv, {**kwargs, "env": dict(kwargs["env"])}))
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert "source-secret" not in " ".join(argv)
        assert "owner-backup-secret" not in " ".join(argv)
        if "-importkeystore" in argv:
            Path(argv[argv.index("-destkeystore") + 1]).write_bytes(b"encrypted-export")
            if fail_import:
                return subprocess.CompletedProcess(argv, 1, "source-secret", "owner-backup-secret")
        fingerprint = "cd" * 32 if wrong_pin or (wrong_reopen and len(calls) == 3) else PIN
        entry = "trustedCertEntry" if certificate_only else "PrivateKeyEntry"
        return subprocess.CompletedProcess(argv, 0, f"Entry type: {entry}\nSHA256: {fingerprint}", "")
    return run


def export(backup, source, destination, **kwargs):
    return backup.export_backup(source, destination, "owner-backup-secret", "source-secret", "release", **kwargs)


def test_export_verifies_reopened_private_key_and_writes_only_public_metadata(backup, source, tmp_path):
    calls = []
    destination = tmp_path / "offline"
    manifest = export(backup, source, destination, runner=fake_runner(calls))
    assert len(calls) == 3
    assert "-importkeystore" in calls[1][0]
    assert calls[2][1]["env"]["CRIER_BACKUP_DEST_PASSWORD"] == "owner-backup-secret"
    assert "-storepass:env" in calls[2][0]
    assert "-srcstorepass:env" in calls[1][0]
    assert "-srckeypass:env" in calls[1][0]
    assert "-deststorepass:env" in calls[1][0]
    assert "-destkeypass:env" in calls[1][0]
    assert manifest["certificate_sha256"] == PIN
    assert manifest["keystore_sha256"] == hashlib.sha256(b"encrypted-export").hexdigest()
    for path in destination.iterdir():
        assert b"source-secret" not in path.read_bytes()
        assert b"owner-backup-secret" not in path.read_bytes()
    assert json.loads((destination / "manifest.json").read_text()) == manifest
    assert (source / "android-release.p12").read_bytes() == b"source-keystore"


@pytest.mark.parametrize("existing", ["file", "populated", "empty"])
def test_existing_destination_is_never_overwritten(backup, source, tmp_path, existing):
    destination = tmp_path / "offline"
    if existing == "file":
        destination.write_text("keep")
    else:
        destination.mkdir()
        if existing == "populated":
            (destination / "keep.txt").write_text("keep")
    calls = []
    with pytest.raises(ValueError, match="new directory"):
        export(backup, source, destination, runner=fake_runner(calls))
    assert destination.exists()
    assert not calls


@pytest.mark.parametrize("options", [{"wrong_pin": True}, {"wrong_reopen": True}, {"certificate_only": True}, {"fail_import": True}])
def test_failure_preserves_source_and_removes_only_new_export(backup, source, tmp_path, options):
    destination = tmp_path / "offline"
    with pytest.raises(ValueError) as error:
        export(backup, source, destination, runner=fake_runner([], **options))
    assert "source-secret" not in str(error.value)
    assert "owner-backup-secret" not in str(error.value)
    assert not destination.exists()
    assert (source / "android-release.p12").read_bytes() == b"source-keystore"


def test_failure_cleanup_preserves_unrelated_file_and_parent_environment(backup, source, tmp_path, monkeypatch):
    monkeypatch.setenv("CRIER_BACKUP_DEST_PASSWORD", "inherited-value")
    destination = tmp_path / "offline"
    runner = fake_runner([], fail_import=True)
    def interrupted_import(argv, **kwargs):
        if "-importkeystore" in argv:
            (destination / "unrelated.txt").write_text("keep")
        return runner(argv, **kwargs)
    with pytest.raises(ValueError):
        export(backup, source, destination, runner=interrupted_import)
    assert (destination / "unrelated.txt").read_text() == "keep"
    assert not (destination / "android-release-backup.p12").exists()
    assert os.environ["CRIER_BACKUP_DEST_PASSWORD"] == "inherited-value"


@pytest.mark.parametrize("password", ["", "short", "has\nnewlines-password", "nul\0password-value"])
def test_invalid_backup_password_fails_before_export(backup, source, tmp_path, password):
    calls = []
    with pytest.raises(ValueError):
        backup.export_backup(source, tmp_path / "offline", password, "source-secret", "release", runner=fake_runner(calls))
    assert not calls


def test_synthetic_keystore_reopens_with_new_password_and_same_certificate(backup, tmp_path):
    keytool = shutil.which("keytool")
    if not keytool:
        pytest.skip("JDK keytool not installed")
    identity = tmp_path / "synthetic"
    identity.mkdir()
    env = dict(os.environ, CRIER_TEST_PASSWORD="synthetic-source-secret")
    args = [keytool, "-genkeypair", "-alias", "synthetic", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "1", "-dname", "CN=Synthetic backup test", "-storetype", "PKCS12",
            "-keystore", str(identity / "android-release.p12"), "-storepass:env", "CRIER_TEST_PASSWORD"]
    subprocess.run(args, env=env, check=True, capture_output=True, stdin=subprocess.DEVNULL)
    info = subprocess.run([keytool, "-J-Duser.language=en", "-list", "-v", "-alias", "synthetic",
                           "-keystore", str(identity / "android-release.p12"), "-storepass:env", "CRIER_TEST_PASSWORD"],
                          env=env, check=True, capture_output=True, text=True)
    pin = backup.certificate_fingerprint(info.stdout)
    (identity / "android-certificate-sha256.txt").write_text(pin)
    destination = tmp_path / "backup"
    result = backup.export_backup(identity, destination, "synthetic-new-password", "synthetic-source-secret", "synthetic", keytool=keytool)
    assert result["certificate_sha256"] == pin
    assert result["keystore_sha256"] != hashlib.sha256((identity / "android-release.p12").read_bytes()).hexdigest()


@pytest.mark.parametrize("answers", [[None], ["owner-backup-secret", None], ["owner-backup-secret", "different"]])
def test_gui_cancel_or_mismatch_never_exports(backup, tmp_path, monkeypatch, answers):
    root = Mock()
    dialog = Mock(side_effect=answers)
    messagebox = Mock()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root, simpledialog=SimpleNamespace(askstring=dialog), messagebox=messagebox))
    monkeypatch.setitem(sys.modules, "tkinter.simpledialog", SimpleNamespace(askstring=dialog))
    destination = tmp_path / "offline"
    assert backup.main(["--gui", "--destination", str(destination)]) == 1
    assert not destination.exists()
    root.destroy.assert_called_once()
    for call in dialog.call_args_list:
        assert call.kwargs["show"] == "*"
    messagebox.showerror.assert_called_once()
    assert "owner-backup-secret" not in str(messagebox.showerror.call_args)


def test_gui_success_feedback_contains_only_public_destination(backup, tmp_path, monkeypatch):
    root, messagebox = Mock(), Mock()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root, messagebox=messagebox))
    monkeypatch.setattr(backup, "request_password", lambda gui: "owner-backup-secret")
    monkeypatch.setattr("crier.device_secrets.load_secret", lambda path: json.dumps({"alias": "release", "password": "source-secret"}))
    engine = Mock()
    monkeypatch.setattr(backup, "export_backup", engine)
    destination = tmp_path / "offline"
    assert backup.main(["--gui", "--destination", str(destination)]) == 0
    messagebox.showinfo.assert_called_once()
    assert str(destination) in messagebox.showinfo.call_args.args[1]
    assert "owner-backup-secret" not in str(messagebox.showinfo.call_args)
    assert "source-secret" not in str(messagebox.showinfo.call_args)

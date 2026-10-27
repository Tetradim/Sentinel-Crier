import base64
import json
from pathlib import Path

import pytest


def test_installer_handoff_keeps_untrusted_paths_out_of_powershell_code(tmp_path):
    from crier.update_install import handoff_command
    installer=tmp_path/"SentinelCrier-'$(bad)-Setup.exe"
    installer.write_bytes(b'synthetic')
    command=handoff_command(installer,'a'*64,[],tmp_path/'result.json',parent_pid=123,powershell='powershell.exe')
    assert command[:5] == ['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden']
    script=base64.b64decode(command[-1]).decode('utf-16le')
    assert str(installer) not in script
    assert 'Wait-Process' in script and 'ComputeHash' in script
    assert script.index('ComputeHash') < script.index('Start-Process')
    assert 'CrierUpdateGuard' in script and '$ancestors' in script
    assert 'ArgumentList' not in script


@pytest.mark.parametrize('digest,pins', [('bad',[]),('a'*64,['not a certificate']),('a'*64,'bad')])
def test_handoff_rejects_invalid_expected_integrity(tmp_path,digest,pins):
    from crier.update_install import handoff_command
    installer=tmp_path/'installer.exe';installer.write_bytes(b'x')
    with pytest.raises(ValueError):handoff_command(installer,digest,pins,tmp_path/'result.json',powershell='powershell.exe')


def test_prepare_reverifies_signed_metadata_after_backup_and_never_uses_a_new_file_hash(tmp_path,monkeypatch):
    from crier import update_install
    events=[]
    installer=tmp_path/'installer.exe';installer.write_bytes(b'changed bytes')
    class Client:
        release={'installer':{'sha256':'b'*64}}
        def verify_staged(self):events.append('verify');return installer
    backup=tmp_path/'backup';backup.mkdir()
    monkeypatch.setattr(update_install,'create_backup',lambda *a,**kw:(events.append('backup') or backup))
    monkeypatch.setattr(update_install,'validate_backup',lambda p:{})
    monkeypatch.setattr(update_install,'handoff_command',lambda path,digest,pins,status,**kw:(events.append(digest) or ['synthetic']))
    plan=update_install.prepare_install(Client(),tmp_path/'profile',tmp_path/'backups',[],tmp_path/'result.json',locked_profile=True)
    assert events==['verify','backup','verify','b'*64]
    assert plan['command']==['synthetic'] and plan['backup']==str(backup)


def test_failed_backup_never_builds_handoff(tmp_path,monkeypatch):
    from crier import update_install
    class Client:
        release={'installer':{'sha256':'b'*64}}
        def verify_staged(self):return tmp_path/'installer.exe'
    monkeypatch.setattr(update_install,'create_backup',lambda *a,**kw:(_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(update_install,'handoff_command',lambda *a,**kw:pytest.fail('must not launch'))
    with pytest.raises(OSError):update_install.prepare_install(Client(),tmp_path/'p',tmp_path/'b',[],tmp_path/'status')


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows installer helper')
@pytest.mark.parametrize('correct', [True,False])
def test_native_helper_verifies_without_executing_any_installer(tmp_path,correct):
    import hashlib,subprocess
    from crier.update_install import handoff_command
    installer=tmp_path/'synthetic.exe';installer.write_bytes(b'not executable')
    status=tmp_path/'result.json'
    digest=hashlib.sha256(installer.read_bytes()).hexdigest() if correct else 'a'*64
    command=handoff_command(installer,digest,[],status,parent_pid=2147483647,verify_only=True)
    result=subprocess.run(command,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0
    assert json.loads(status.read_text(encoding='utf-8-sig'))['status']==('verified' if correct else 'verification_or_install_failed')

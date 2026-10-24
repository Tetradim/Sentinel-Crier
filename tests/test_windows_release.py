from pathlib import Path
import importlib.util
import json
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_metadata', ROOT / 'desktop' / 'release_metadata.py')


def metadata():
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_is_per_user_and_never_removes_user_state():
    source = (ROOT / 'desktop' / 'SentinelCrier.iss').read_text()
    assert 'PrivilegesRequired=lowest' in source
    assert 'DefaultDirName={localappdata}\\Programs\\SentinelCrier' in source
    assert 'AppId={{24760C0D-9A32-46E7-A9EE-BBF3C2EA51AF}' in source
    assert 'CloseApplications=no' in source
    assert '[UninstallDelete]' not in source
    assert 'SentinelCrier\\Desktop' not in source
    assert 'Source: "{#SourceDir}\\*"; DestDir: "{app}"' in source
    assert "CreateFileW@kernel32.dll stdcall" in source
    assert 'OpenProgram(ProgramFile, $40000000, 0, 0, 3, 0, 0)' in source
    assert 'ComparePackedVersion' in source


@pytest.mark.parametrize('version', ['1.2', 'v1.2.3', '01.2.3', '1.2.3-beta', '1.2.3+build', '65536.0.0'])
def test_version_rejects_ambiguous_or_unrepresentable_installer_versions(version):
    with pytest.raises(ValueError):
        metadata().validate_version(version)


def test_release_manifest_hashes_actual_artifacts_and_includes_public_configuration(tmp_path):
    module = metadata()
    installer = tmp_path / 'SentinelCrier-0.2.0-Windows-Setup.exe'
    portable = tmp_path / 'SentinelCrier-0.2.0-Windows.zip'
    installer.write_bytes(b'installer')
    portable.write_bytes(b'portable')
    manifest = module.make_manifest('0.2.0', 'a' * 40, 'https://relay.example/crier', [installer, portable], 'unsigned')
    assert manifest['version'] == '0.2.0'
    assert manifest['platform'] == 'windows-x64'
    assert manifest['commit'] == 'a' * 40
    assert manifest['connection_service_url'] == 'https://relay.example/crier'
    assert manifest['authenticode'] == 'unsigned'
    import hashlib
    assert manifest['artifacts'][installer.name]['sha256'] == hashlib.sha256(b'installer').hexdigest()
    assert manifest['artifacts'][portable.name]['bytes'] == 8


def test_build_keeps_configuration_and_version_in_distribution():
    source = (ROOT / 'desktop' / 'build.ps1').read_text()
    assert "crier/connection-service.json" in source
    assert "release.json" in source
    release = (ROOT / 'desktop' / 'release.ps1').read_text()
    assert 'release_metadata.py' in release
    assert 'Set-AuthenticodeSignature' in release
    assert 'EphemeralKeySet' in release
    workflow = (ROOT / '.github' / 'workflows' / 'windows-release.yml').read_text()
    assert 'workflow_dispatch:' in workflow
    assert 'python -m pytest -q' in workflow
    assert 'release.ps1' in workflow
    assert 'secrets.WINDOWS_SIGNING_PFX_BASE64' in workflow


@pytest.mark.parametrize('url', ['http://relay.example', 'https://key:secret@relay.example', 'https://relay.example?token=secret', 'https://relay.example/#secret'])
def test_manifest_rejects_secret_bearing_or_insecure_service_urls(tmp_path, url):
    with pytest.raises(ValueError):
        metadata().make_manifest('0.2.0', 'a' * 40, url, [], 'unsigned')


def test_release_metadata_is_copied_without_local_credentials():
    source = (ROOT / 'desktop' / 'build.ps1').read_text()
    assert 'dist/SentinelCrier/release.json' in source
    assert 'LOCALAPPDATA' not in source
    assert 'desktop-credentials' not in source

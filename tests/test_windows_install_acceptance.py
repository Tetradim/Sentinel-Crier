"""Portable safety and command tests; never run installers or touch the registry."""
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

SPEC = importlib.util.spec_from_file_location(
    'windows_acceptance', Path(__file__).resolve().parents[1] / 'scripts/windows-install-acceptance.py')


def harness():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


@pytest.mark.parametrize('version', ['0.2', 'v0.2.0', '01.2.0', '0.2.65535', '0.2.0-beta'])
def test_patch_rejects_ambiguous_or_overflow_versions(version):
    with pytest.raises(ValueError):
        harness().next_patch(version)


def test_patch_and_installer_name():
    m = harness()
    assert m.next_patch('0.2.0') == '0.2.1'
    assert m.installer_version(Path('SentinelCrier-0.2.0-Windows-Setup.exe')) == '0.2.0'
    with pytest.raises(ValueError):
        m.installer_version(Path('arbitrary.exe'))


def test_guard_requires_hosted_windows_and_fresh_data(tmp_path):
    m = harness()
    env = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
               RUNNER_TEMP=str(tmp_path), LOCALAPPDATA=str(tmp_path / 'local'))
    for name, changes in [('posix', {}), ('nt', {'GITHUB_ACTIONS': 'false'}),
                          ('nt', {'RUNNER_ENVIRONMENT': 'self-hosted'}),
                          ('nt', {'RUNNER_TEMP': ''})]:
        with pytest.raises(RuntimeError):
            m.guard_runner(dict(env, **changes), name, [])
    assert m.guard_runner(env, 'nt', []) == tmp_path.resolve()
    with pytest.raises(RuntimeError):
        m.guard_runner(env, 'nt', [{'DisplayName': 'Sentinel Crier'}])
    data = tmp_path / 'local/SentinelCrier/Desktop'
    data.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        m.guard_runner(env, 'nt', [])


def test_paths_refuse_escape_and_root(tmp_path):
    m = harness()
    assert m.owned_child(tmp_path / 'acceptance/program', tmp_path) == (tmp_path / 'acceptance/program').resolve()
    for path in [tmp_path, tmp_path / '../outside']:
        with pytest.raises(RuntimeError):
            m.owned_child(path, tmp_path)


def test_silent_commands_and_bounded_hidden_subprocess(tmp_path):
    m = harness()
    command = m.install_command(tmp_path / 'setup.exe', tmp_path / 'program', tmp_path / 'install.log')
    assert command[1:5] == ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-']
    assert '/DIR=' + str(tmp_path / 'program') in command
    fake = Mock(return_value=subprocess.CompletedProcess(command, 5))
    records = []
    assert m.run_command(command, records, runner=fake, windows=False) == 5
    kwargs = fake.call_args.kwargs
    assert kwargs['timeout'] == 240
    assert kwargs['shell'] is False
    assert records == [{'executable': 'setup.exe', 'returncode': 5}]


def test_parser_requires_all_release_inputs():
    m = harness()
    with pytest.raises(SystemExit):
        m.parser().parse_args([])
    args = m.parser().parse_args(['--installer', 'base.exe', '--compiler', 'ISCC.exe',
                                  '--program-source', 'dist/SentinelCrier', '--output', 'report.json'])
    assert str(args.output) == 'report.json'


def test_refused_main_never_reads_registry_or_runs_commands(tmp_path, monkeypatch):
    m = harness()
    def refuse(*args):
        raise RuntimeError('hosted runner required')
    forbidden = Mock(side_effect=AssertionError('unsafe operation before guard'))
    monkeypatch.setattr(m, 'guard_runner', refuse)
    monkeypatch.setattr(m, 'registry_entries', forbidden)
    monkeypatch.setattr(m, 'run_command', forbidden)
    output = tmp_path / 'report.json'
    assert m.main(['--installer', 'base.exe', '--compiler', 'ISCC.exe',
                   '--program-source', 'dist/SentinelCrier', '--output', str(output)]) == 1
    forbidden.assert_not_called()
    import json
    report = json.loads(output.read_text())
    assert report['status'] == 'failed'
    assert report['physical_customer_machine_verified'] is False
    assert report['commands'] == []


def test_install_verification_rejects_registry_and_payload_changes(tmp_path, monkeypatch):
    m = harness()
    program = tmp_path / 'program'
    program.mkdir()
    (program / 'SentinelCrier.exe').write_bytes(b'synthetic executable')
    (program / 'unins000.exe').write_bytes(b'synthetic uninstaller')
    payload = {'SentinelCrier.exe': m.digest(program / 'SentinelCrier.exe')}
    entries = [{'DisplayVersion': '0.2.1', 'InstallLocation': str(program)}]
    monkeypatch.setattr(m, 'registry_entries', lambda: entries)
    m.verify_install(program.resolve(), '0.2.1', payload)
    with pytest.raises(RuntimeError):
        m.verify_install(program.resolve(), '0.2.0', payload)
    entries[0]['InstallLocation'] = str(tmp_path / 'unowned')
    with pytest.raises(RuntimeError):
        m.verify_install(program.resolve(), '0.2.1', payload)
    entries[0]['InstallLocation'] = str(program)
    (program / 'SentinelCrier.exe').write_bytes(b'mutated')
    with pytest.raises(RuntimeError):
        m.verify_install(program.resolve(), '0.2.1', payload)


def test_windows_commands_hide_windows_and_propagate_timeout(monkeypatch):
    m = harness()
    class Startup:
        dwFlags = 0
    monkeypatch.setattr(m.subprocess, 'STARTUPINFO', Startup, raising=False)
    monkeypatch.setattr(m.subprocess, 'STARTF_USESHOWWINDOW', 1, raising=False)
    monkeypatch.setattr(m.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    runner = Mock(return_value=subprocess.CompletedProcess(['setup.exe'], 0))
    m.run_command(['setup.exe'], [], runner=runner, windows=True)
    assert runner.call_args.kwargs['startupinfo'].wShowWindow == 0
    assert runner.call_args.kwargs['creationflags'] == 0x08000000
    runner.side_effect = subprocess.TimeoutExpired('setup.exe', 240)
    with pytest.raises(subprocess.TimeoutExpired):
        m.run_command(['setup.exe'], [], runner=runner, windows=True)

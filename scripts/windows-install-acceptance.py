"""Actual installer acceptance, exclusively on fresh GitHub-hosted Windows runners.

No desktop or broker executable is launched. Synthetic user data is intentionally
retained for runner disposal; this script never recursively deletes any path.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
APP_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{24760C0D-9A32-46E7-A9EE-BBF3C2EA51AF}_is1'
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def next_patch(version):
    if not re.fullmatch(VERSION, version):
        raise ValueError('Expected canonical three-part release version')
    parts = [int(x) for x in version.split('.')]
    if max(parts) > 65535 or parts[2] >= 65535:
        raise ValueError('Next patch exceeds installer version limits')
    parts[2] += 1
    return '.'.join(map(str, parts))


def installer_version(path):
    match = re.fullmatch(r'SentinelCrier-(' + VERSION + r')-Windows-Setup\.exe', path.name)
    if not match:
        raise ValueError('Unexpected release installer filename')
    next_patch(match[1])
    return match[1]


def owned_child(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    if path == parent or not path.is_relative_to(parent):
        raise RuntimeError('Acceptance path must be strictly beneath runner temporary directory')
    return path


def guard_runner(env, platform, existing):
    if platform != 'nt' or env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Actual installer acceptance requires a GitHub-hosted Windows runner')
    temp = Path(env.get('RUNNER_TEMP', ''))
    local = Path(env.get('LOCALAPPDATA', ''))
    if not env.get('RUNNER_TEMP') or not temp.is_absolute() or not temp.is_dir():
        raise RuntimeError('Missing absolute existing RUNNER_TEMP')
    if not env.get('LOCALAPPDATA') or not local.is_absolute():
        raise RuntimeError('Missing absolute LOCALAPPDATA')
    if existing or (local / 'SentinelCrier/Desktop').exists():
        raise RuntimeError('Runner contains existing Sentinel Crier installation or desktop data')
    return temp.resolve()


def registry_entries():
    import winreg
    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, APP_KEY.rsplit('\\', 1)[0], 0, winreg.KEY_READ | view) as root:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(root, index)
                        except OSError as exc:
                            if exc.winerror == 259:
                                break
                            raise
                        index += 1
                        with winreg.OpenKey(root, name) as key:
                            values = {}
                            for field in ('DisplayName', 'DisplayVersion', 'InstallLocation'):
                                try:
                                    values[field] = winreg.QueryValueEx(key, field)[0]
                                except FileNotFoundError:
                                    pass
                            label = (name + str(values.get('DisplayName', ''))).lower().replace(' ', '').replace('-', '')
                            if 'sentinelcrier' in label or name == APP_KEY.rsplit('\\', 1)[1]:
                                values['key'] = name
                                found.append(values)
            except FileNotFoundError:
                pass
    return found


def actual_local_appdata():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 28, None, 0, buffer):
        raise RuntimeError('Cannot resolve actual Windows LocalAppData')
    return Path(buffer.value).resolve()


def install_command(installer, program, log):
    return [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
            '/DIR=' + str(program), '/LOG=' + str(log)]


def run_command(command, records, *, runner=None, windows=None):
    runner = runner or subprocess.run
    windows = os.name == 'nt' if windows is None else windows
    options = dict(timeout=240, shell=False, check=False, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    if windows:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options.update(startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
    result = runner(command, **options)
    records.append(dict(executable=Path(command[0]).name, returncode=result.returncode))
    return result.returncode


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def program_hashes(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob('*') if p.is_file()}


def seed_data(folder):
    sys.path.insert(0, str(ROOT))
    from crier.intent_engine import IntentEngine
    from crier.device_secrets import save_secret
    folder.mkdir(parents=True, exist_ok=False)
    journal = folder / 'intent-acceptance.sqlite3'
    # Initialize the real journal schema without a broker or worker.
    IntentEngine(journal, broker=None)
    with sqlite3.connect(journal) as db:
        db.execute('INSERT INTO intent_orders VALUES (?,?,?,?,?,?,?,?)',
                   ('acceptance-only', 'synthetic-trade', 1, 'buy', '1', 'unknown', None, '0'))
    credential = folder / 'desktop-credentials.secret'
    dummy = json.dumps({'acceptance_only': True, 'dummy': 'synthetic-not-a-broker-credential'})
    save_secret(credential, dummy)
    if not credential.read_bytes().startswith(b'dpapi:'):
        raise RuntimeError('Synthetic credential was not protected by Windows DPAPI')
    return journal, credential, dummy


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_data(journal, credential, dummy, hashes):
    from crier.device_secrets import load_secret
    require([digest(journal), digest(credential)] == hashes, 'User data bytes changed')
    require(load_secret(credential) == dummy, 'DPAPI dummy credential no longer decrypts')
    with sqlite3.connect(f'file:{journal.as_posix()}?mode=ro', uri=True) as db:
        count = db.execute("SELECT count(*) FROM intent_orders WHERE status='unknown'").fetchone()[0]
    require(count == 1, 'Synthetic unresolved order was not retained')
    return dict(journal_sha256=hashes[0], credential_sha256=hashes[1],
                unresolved_order_count=count, dpapi_decryption_verified=True)


def verify_install(program, version, expected):
    entries = registry_entries()
    require(bool(entries), 'Installer uninstall registration is missing')
    require(all(row.get('DisplayVersion') == version and
                Path(row.get('InstallLocation', '')).resolve() == program for row in entries),
            'Installed registry version/location differs')
    require((program / 'SentinelCrier.exe').is_file() and (program / 'unins000.exe').is_file(),
            'Installed executable or uninstaller missing')
    require(all((program / path).is_file() and digest(program / path) == checksum
                for path, checksum in expected.items()), 'Installed program payload differs')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ('installer', 'compiler', 'program-source', 'output'):
        result.add_argument('--' + name, required=True, type=Path)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    report = dict(evidence_scope='ephemeral GitHub-hosted Windows runner',
                  physical_customer_machine_verified=False,
                  upgrade_scope='Same program payload with acceptance-only next patch installer; no future application migration claim.',
                  status='failed', commands=[], stages=[])
    program = None
    install_owned = False
    try:
        # Platform/environment check precedes all registry and Windows API access.
        temp = guard_runner(os.environ, os.name, [])
        require(actual_local_appdata() == Path(os.environ['LOCALAPPDATA']).resolve(),
                'LOCALAPPDATA differs from the actual Windows user data location')
        guard_runner(os.environ, os.name, registry_entries())
        from crier.desktop_presence import RunRegistry, StartupRegistration
        startup_registry = RunRegistry()
        require(startup_registry.get() is None, 'Runner contains existing Crier startup registration')
        installer, compiler, source = args.installer.resolve(), args.compiler.resolve(), args.program_source.resolve()
        require(installer.is_file() and compiler.is_file() and (source / 'SentinelCrier.exe').is_file(),
                'Release installer, compiler or actual desktop payload missing')
        base = installer_version(installer)
        upgraded = next_patch(base)
        work = owned_child(Path(tempfile.mkdtemp(prefix='sentinel-install-acceptance-', dir=temp)), temp)
        program = owned_child(work / 'program', temp)
        build = owned_child(work / 'next-patch', temp)
        build.mkdir()
        require(not build.is_relative_to(ROOT / 'dist/release'), 'Acceptance installer must be outside release artifacts')
        expected = program_hashes(source)
        require(bool(expected), 'Program source is empty')
        journal, credential, dummy = seed_data(actual_local_appdata() / 'SentinelCrier/Desktop')
        hashes = [digest(journal), digest(credential)]
        report.update(base_version=base, upgrade_version=upgraded, source_file_count=len(expected),
                      initial_data=verify_data(journal, credential, dummy, hashes))
        compile_command = [str(compiler), '/O' + str(build), '/DAppVersion=' + upgraded,
                           '/DSourceDir=' + str(source), str(ROOT / 'desktop/SentinelCrier.iss')]
        require(run_command(compile_command, report['commands']) == 0, 'Acceptance installer compilation failed')
        next_installer = build / f'SentinelCrier-{upgraded}-Windows-Setup.exe'
        require(next_installer.is_file(), 'Compiled acceptance installer missing')
        # The unique absent directory and clean registry establish ownership even
        # when an installer partially succeeds before returning an error.
        install_owned = True
        for label, payload, version in [('install', installer, base), ('upgrade', next_installer, upgraded)]:
            require(run_command(install_command(payload, program, work / (label + '.log')),
                                report['commands']) == 0, label + ' failed')
            verify_install(program, version, expected)
            startup = StartupRegistration(program / 'SentinelCrier.exe', frozen=True)
            if label == 'install':
                require(not startup.enabled and startup_registry.get() is None, 'Installer enabled sign-in startup')
                startup.set_enabled(True)
            require(startup.enabled, 'Explicit sign-in registration was lost during install/upgrade')
            report['stages'].append(dict(stage=label, version=version,
                                         startup_opt_in_preserved=True,
                                         data=verify_data(journal, credential, dummy, hashes)))
        before = program_hashes(program)
        code = run_command(install_command(installer, program, work / 'downgrade.log'), report['commands'])
        require(code != 0, 'Old installer unexpectedly allowed downgrade')
        verify_install(program, upgraded, expected)
        require(program_hashes(program) == before, 'Rejected downgrade changed installed files')
        report['stages'].append(dict(stage='downgrade_rejected', returncode=code,
                                     data=verify_data(journal, credential, dummy, hashes)))
        require(run_command([str(program / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                             '/NORESTART', '/LOG=' + str(work / 'uninstall.log')], report['commands']) == 0,
                'Uninstall failed')
        # Inno's original uninstaller process may return before its temporary copy.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and (program.exists() or registry_entries()):
            time.sleep(0.25)
        require(not program.exists() and not registry_entries(), 'Uninstall left program files or registration')
        require(startup_registry.get() is None, 'Uninstall left Crier sign-in registration')
        install_owned = False
        report['stages'].append(dict(stage='uninstall', program_removed=True, uninstall_registry_removed=True,
                                     data=verify_data(journal, credential, dummy, hashes)))
        report['startup'] = dict(default_off=True, explicit_opt_in=True, preserved_on_upgrade=True, removed_on_uninstall=True)
        report['status'] = 'passed'
    except Exception as exc:
        # Exception type only: no credentials, raw registry values or subprocess output.
        report['failure_type'] = type(exc).__name__
        print('Installer acceptance failed: ' + str(exc), file=sys.stderr)
    finally:
        if install_owned and program is not None and (program / 'unins000.exe').is_file():
            try:
                report['cleanup_returncode'] = run_command([str(program / 'unins000.exe'), '/VERYSILENT',
                    '/SUPPRESSMSGBOXES', '/NORESTART'], report['commands'])
            except Exception as exc:
                report['cleanup_failure_type'] = type(exc).__name__
        report['retention'] = 'Any acceptance-owned synthetic user data and evidence are retained for ephemeral runner disposal by GitHub.'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())


"""Release metadata from checked-in public inputs; never reads desktop user data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def validate_version(version):
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Release version must be stable SemVer MAJOR.MINOR.PATCH')
    if any(int(part) > 65535 for part in version.split('.')):
        raise ValueError('Release version components must fit Windows version fields')
    return version


def release_version():
    version = validate_version(json.loads((ROOT / 'release.json').read_text())['version'])
    if tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'] != version:
        raise ValueError('pyproject.toml and release.json versions differ')
    return version


def make_manifest(version, commit, service_url, artifacts, signing):
    validate_version(version)
    url = urlsplit(service_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Packaged service configuration must be a public HTTPS URL without secrets')
    if signing not in ('unsigned', 'signed'):
        raise ValueError('Unknown Authenticode state')
    return dict(version=version, commit=commit, platform='windows-x64',
                release_channel='candidate', physical_device_acceptance='deferred_by_owner',
                connection_service_url=service_url, authenticode=signing,
                artifacts={p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                           for p in artifacts})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version-only', action='store_true')
    parser.add_argument('--signing', choices=['unsigned', 'signed'], default='unsigned')
    parser.add_argument('--output', type=Path)
    parser.add_argument('artifacts', nargs='*', type=Path)
    args = parser.parse_args()
    version = release_version()
    if args.version_only:
        print(version)
    else:
        if not args.output or not args.artifacts:
            parser.error('--output and release artifacts are required')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        service = json.loads((ROOT / 'crier' / 'connection-service.json').read_text())['url']
        result = make_manifest(version, commit, service, args.artifacts, args.signing)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')

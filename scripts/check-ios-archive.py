"""Verify unsigned device Release archive resources; never declares signing valid."""
import argparse
import json
from pathlib import Path
import plistlib


def validate_archive(archive, release, service):
    apps = list((Path(archive) / 'Products/Applications').glob('*.app'))
    if len(apps) != 1:
        raise ValueError('Expected exactly one device application in archive')
    app = apps[0]
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    if (info.get('CFBundleIdentifier') != 'com.tetradim.sentinelcrier'
            or info.get('CFBundleShortVersionString') != release['version']
            or str(info.get('CFBundleVersion')) != str(release['ios']['minimum_build_number'])):
        raise ValueError('Archive identity/version does not match release configuration')
    if info.get('DTPlatformName') != 'iphoneos' or info.get('CFBundleSupportedPlatforms') != ['iPhoneOS']:
        raise ValueError('Expected device platform, not simulator')
    executable = info.get('CFBundleExecutable')
    if not isinstance(executable, str) or not executable or '/' in executable or '\\' in executable:
        raise ValueError('Invalid application executable')
    for name in (executable, 'Assets.car'):
        if not (app / name).is_file() or not (app / name).stat().st_size:
            raise ValueError('Missing compiled application resource')
    icon = info.get('CFBundleIcons', {}).get('CFBundlePrimaryIcon', {})
    if not icon.get('CFBundleIconFiles'):
        raise ValueError('Missing compiled app icon metadata')
    privacy = plistlib.loads((app / 'PrivacyInfo.xcprivacy').read_bytes())
    usage = privacy.get('NSPrivacyAccessedAPITypes', [])
    if (privacy.get('NSPrivacyTracking') is not False or not any(
            item.get('NSPrivacyAccessedAPIType') == 'NSPrivacyAccessedAPICategoryUserDefaults'
            and 'CA92.1' in item.get('NSPrivacyAccessedAPITypeReasons', []) for item in usage)):
        raise ValueError('Missing expected settings privacy declaration')
    if json.loads((app / 'connection-service.json').read_text()) != service:
        raise ValueError('Packaged connection service does not match checked-in configuration')
    return dict(checks_passed=True, platform='iphoneos', version=release['version'],
                build_number=info['CFBundleVersion'], signing='not_verified',
                installable_package=False, physical_acceptance='deferred_by_owner')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = validate_archive(args.archive, json.loads((root / 'release.json').read_text()),
                              json.loads((root / 'crier/connection-service.json').read_text()))
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Unsigned iPhone archive resources verified; signing and installation remain unverified.')

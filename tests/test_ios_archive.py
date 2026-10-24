import importlib.util
import json
from pathlib import Path
import plistlib

import pytest

spec = importlib.util.spec_from_file_location('ios_archive', Path(__file__).resolve().parents[1] / 'scripts/check-ios-archive.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def archive(tmp_path):
    app = tmp_path / 'Crier.xcarchive/Products/Applications/SentinelCrier.app'
    app.mkdir(parents=True)
    info = dict(CFBundleIdentifier='com.tetradim.sentinelcrier',
                CFBundleShortVersionString='0.2.0', CFBundleVersion='1',
                CFBundleExecutable='SentinelCrier', DTPlatformName='iphoneos',
                CFBundleSupportedPlatforms=['iPhoneOS'],
                CFBundleIcons={'CFBundlePrimaryIcon': {'CFBundleIconFiles': ['AppIcon60x60']}})
    (app / 'Info.plist').write_bytes(plistlib.dumps(info))
    (app / 'SentinelCrier').write_bytes(b'compiled-executable-fixture')
    (app / 'Assets.car').write_bytes(b'compiled-assets-fixture')
    (app / 'PrivacyInfo.xcprivacy').write_bytes(plistlib.dumps({'NSPrivacyTracking': False,
        'NSPrivacyAccessedAPITypes': [{'NSPrivacyAccessedAPIType': 'NSPrivacyAccessedAPICategoryUserDefaults',
                                      'NSPrivacyAccessedAPITypeReasons': ['CA92.1', '1C8F.1']}]}))
    (app / 'connection-service.json').write_text(json.dumps({'url': 'https://relay.example'}))
    return tmp_path / 'Crier.xcarchive', app


def validate(path):
    return module.validate_archive(path, {'version': '0.2.0', 'ios': {'minimum_build_number': 1}},
                                   {'url': 'https://relay.example'})


def test_device_archive_report_is_not_distribution_evidence(archive):
    path, _ = archive
    result = validate(path)
    assert result['checks_passed'] is True
    assert result['signing'] == 'not_verified'
    assert result['installable_package'] is False
    assert result['platform'] == 'iphoneos'


@pytest.mark.parametrize('filename', ['PrivacyInfo.xcprivacy', 'connection-service.json', 'Assets.car', 'SentinelCrier'])
def test_missing_bundle_resources_fail(archive, filename):
    path, app = archive
    (app / filename).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        validate(path)


@pytest.mark.parametrize('field,value', [('CFBundleIdentifier', 'wrong.app'),
    ('CFBundleShortVersionString', '0.1.0'), ('CFBundleVersion', '0'),
    ('DTPlatformName', 'iphonesimulator'), ('CFBundleIcons', {}),
    ('CFBundleExecutable', '../outside')])
def test_wrong_identity_or_device_metadata_rejected(archive, field, value):
    path, app = archive
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    info[field] = value
    (app / 'Info.plist').write_bytes(plistlib.dumps(info))
    with pytest.raises(ValueError):
        validate(path)


def test_wrong_packaged_service_rejected(archive):
    path, app = archive
    (app / 'connection-service.json').write_text('{"url":"https://wrong.example"}')
    with pytest.raises(ValueError):
        validate(path)

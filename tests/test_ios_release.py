"""Portable signing preflight tests using simulated decoded Apple plists."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import plistlib
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ios_release", ROOT / "scripts/ios-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def profile():
    # Round-trip fixture through plistlib exactly as security cms decoded output.
    return plistlib.loads(plistlib.dumps({
        "UUID": "fixture-profile", "TeamIdentifier": ["TEAM123"],
        "ApplicationIdentifierPrefix": ["TEAM123"], "DeveloperCertificates": [b"fixture-public-cert"],
        "ExpirationDate": dt.datetime(2099, 1, 1),
        "Entitlements": {"application-identifier": "TEAM123." + release.BUNDLE,
                         "com.apple.developer.team-identifier": "TEAM123", "get-task-allow": False,
                         "keychain-access-groups": ["TEAM123." + release.BUNDLE, "TEAM123." + release.BUNDLE + ".shared"],
                         "com.apple.security.application-groups": [release.GROUP]},
    }))


@pytest.mark.parametrize("method,devices,development", [
    ("app-store-connect", False, False), ("release-testing", True, False), ("debugging", True, True)])
def test_profile_types(profile, method, devices, development):
    profile["Entitlements"]["get-task-allow"] = development
    if devices:
        profile["ProvisionedDevices"] = ["fixture-device"]
    assert release.validate_profile(profile, "TEAM123", method)["method"] == method

def test_matching_keychain_prefix_wildcard_authorizes_concrete_app_groups(profile):
    profile["Entitlements"]["keychain-access-groups"] = ["TEAM123.*"]
    assert release.validate_profile(profile,"TEAM123","app-store-connect")["method"] == "app-store-connect"


@pytest.mark.parametrize("change", ["team", "entitlement_team", "appid", "keychain", "appgroup", "expiry", "enterprise", "wrong_type"])
def test_rejects_bad_profile(profile, change):
    if change == "team": profile["TeamIdentifier"] = ["OTHER"]
    if change == "entitlement_team": profile["Entitlements"]["com.apple.developer.team-identifier"] = "OTHER"
    if change == "appid": profile["Entitlements"]["application-identifier"] = "OTHER." + release.BUNDLE
    if change == "keychain": profile["Entitlements"]["keychain-access-groups"] = ["OTHERTEAM.*"]
    if change == "appgroup": profile["Entitlements"]["com.apple.security.application-groups"] = []
    if change == "expiry": profile["ExpirationDate"] = dt.datetime(2020, 1, 1)
    if change == "enterprise": profile["ProvisionsAllDevices"] = True
    if change == "wrong_type": profile["ProvisionedDevices"] = ["device"]
    with pytest.raises(ValueError):
        release.validate_profile(profile, "TEAM123", "app-store-connect")


def test_missing_secret_values_never_printed():
    secrets = {name: "secret-must-not-appear" for name in release.SIGNING_SECRETS}
    secrets.pop("P12_PASSWORD")
    with pytest.raises(ValueError) as error:
        release.preflight(secrets)
    assert "P12_PASSWORD" in str(error.value)
    assert "secret-must-not-appear" not in str(error.value)


def test_optional_upload_requires_separate_api_secrets_and_correct_method():
    secrets = {name: "present" for name in release.SIGNING_SECRETS}
    release.preflight(secrets)
    with pytest.raises(ValueError): release.preflight(secrets, True)
    secrets.update({name: "present" for name in release.API_SECRETS})
    release.preflight(secrets, True)
    with pytest.raises(ValueError): release.preflight(secrets, True, "debugging")


def test_build_numbers_never_reset_previous_upload():
    config = {"version": "0.2.0", "ios": {"minimum_build_number": 5}}
    assert release.versions(config, "12", "11") == ("0.2.0", 12)
    for build, previous in [(5, 5), (4, 0), (1, 50), (10, -1)]:
        with pytest.raises(ValueError): release.versions(config, build, previous)


def test_ipa_manifest_checks_actual_bundle_and_records_provenance(tmp_path):
    ipa = tmp_path / "Crier.ipa"
    def write(version):
        with zipfile.ZipFile(ipa, "w") as package:
            package.writestr("Payload/Crier.app/Info.plist", plistlib.dumps({
                "CFBundleIdentifier": release.BUNDLE, "CFBundleShortVersionString": version, "CFBundleVersion": "12"}))
    write("0.2.0")
    result = release.manifest(ipa, "0.2.0", 12, "commit", "https://example.com", {"certificate": {"sha256": "public"}})
    assert len(result["sha256"]) == 64
    assert result["commit"] == "commit" and result["public_endpoint"] == "https://example.com"
    assert result["physical_device_acceptance"] == "deferred"
    write("0.1.0")
    with pytest.raises(ValueError): release.manifest(ipa, "0.2.0", 12, "commit", "url", {})


def test_project_defaults_follow_release_source():
    config = json.loads((ROOT / "release.json").read_text())
    defaults = (ROOT / "ios/ReleaseVersion.xcconfig").read_text()
    assert "MARKETING_VERSION = " + config["version"] in defaults
    assert "CURRENT_PROJECT_VERSION = " + str(config["ios"]["minimum_build_number"]) in defaults

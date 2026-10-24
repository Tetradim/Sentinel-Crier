"""Offline release validation; never prints secret values or writes private keys."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import zipfile

BUNDLE = "com.tetradim.sentinelcrier"
GROUP = "group." + BUNDLE
SIGNING_SECRETS = ("APPLE_TEAM_ID", "BUILD_CERTIFICATE_BASE64", "P12_PASSWORD",
                   "BUILD_PROVISION_PROFILE_BASE64", "KEYCHAIN_PASSWORD")
API_SECRETS = ("APP_STORE_CONNECT_KEY_ID", "APP_STORE_CONNECT_ISSUER_ID", "APP_STORE_CONNECT_PRIVATE_KEY_BASE64")


def preflight(env, upload=False, method="app-store-connect"):
    missing = [name for name in SIGNING_SECRETS + (API_SECRETS if upload else ()) if not env.get(name)]
    if missing:
        raise ValueError("Release blocked: missing environment secrets: " + ", ".join(missing))
    if upload and method != "app-store-connect":
        raise ValueError("TestFlight upload requires app-store-connect export")


def versions(release, build, previous):
    version = release["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid release version")
    build, previous = int(build), int(previous)
    floor = int(release.get("ios", {}).get("minimum_build_number", 1))
    if build < floor or build <= previous or build < 1 or previous < 0:
        raise ValueError("Build must exceed the owner-confirmed previous upload and meet release floor")
    return version, build


def validate_profile(profile, team, method, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    ent = profile.get("Entitlements", {})
    if profile.get("TeamIdentifier") != [team] or ent.get("com.apple.developer.team-identifier") != team:
        raise ValueError("Wrong signing team")
    prefixes = profile.get("ApplicationIdentifierPrefix", [])
    if len(prefixes) != 1 or ent.get("application-identifier") != prefixes[0] + "." + BUNDLE:
        raise ValueError("Expected exact application identifier")
    prefix = prefixes[0]
    required_keys = {prefix + "." + BUNDLE, prefix + "." + BUNDLE + ".shared"}
    allowed = set(ent.get("keychain-access-groups", []))
    if not all(group in allowed or prefix + ".*" in allowed for group in required_keys):
        raise ValueError("Missing authorization for shared Keychain groups")
    if GROUP not in ent.get("com.apple.security.application-groups", []):
        raise ValueError("Missing exact App Group")
    expiry = profile.get("ExpirationDate")
    if not isinstance(expiry, dt.datetime) or expiry.replace(tzinfo=dt.timezone.utc) <= now:
        raise ValueError("Expired or missing profile expiration")
    devices = bool(profile.get("ProvisionedDevices"))
    development = ent.get("get-task-allow") is True
    if profile.get("ProvisionsAllDevices"):
        raise ValueError("Enterprise profile unsupported")
    expected = {"debugging": devices and development,
                "release-testing": devices and not development,
                "app-store-connect": not devices and not development}.get(method, False)
    if not expected:
        raise ValueError("Provisioning profile type does not match export method")
    if not profile.get("UUID") or not profile.get("DeveloperCertificates"):
        raise ValueError("Missing profile identity or signing certificates")
    return {"uuid": profile["UUID"], "expires_at": expiry.isoformat() + "Z", "method": method,
            "team_id": team, "application_identifier": ent["application-identifier"]}


def certificate_metadata(path, profile):
    result = subprocess.run(["openssl", "pkcs12", "-in", str(path), "-clcerts", "-nokeys",
                             "-passin", "env:P12_PASSWORD"], capture_output=True, check=True)
    pem = result.stdout
    der = subprocess.run(["openssl", "x509", "-outform", "DER"], input=pem,
                         capture_output=True, check=True).stdout
    fingerprint = hashlib.sha256(der).hexdigest()
    if not any(hashlib.sha256(cert).hexdigest() == fingerprint for cert in profile["DeveloperCertificates"]):
        raise ValueError("Signing certificate is not authorized by profile")
    subprocess.run(["openssl", "x509", "-checkend", "0", "-noout"], input=pem,
                   capture_output=True, check=True)
    info = subprocess.run(["openssl", "x509", "-noout", "-subject", "-issuer", "-serial", "-dates"],
                          input=pem, capture_output=True, check=True).stdout.decode()
    return {"sha256": fingerprint, "metadata": info.strip().splitlines()}


def manifest(ipa, version, build, commit, endpoint, signing):
    with zipfile.ZipFile(ipa) as package:
        infos = [n for n in package.namelist() if re.fullmatch(r"Payload/[^/]+\.app/Info.plist", n)]
        if len(infos) != 1:
            raise ValueError("Expected one app Info.plist")
        info = plistlib.loads(package.read(infos[0]))
    if (info.get("CFBundleIdentifier"), info.get("CFBundleShortVersionString"), str(info.get("CFBundleVersion"))) != (BUNDLE, version, str(build)):
        raise ValueError("Exported IPA identity/version does not match requested release")
    return {"schema": "crier.ios-release.v1", "ipa": ipa.name, "sha256": hashlib.sha256(ipa.read_bytes()).hexdigest(),
            "commit": commit, "version": version, "build_number": build, "public_endpoint": endpoint,
            "signing": signing, "physical_device_acceptance": "deferred", "apple_processing": "not_verified"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["preflight", "profile", "manifest"])
    parser.add_argument("--method", default="app-store-connect")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root
    release = json.loads((root / "release.json").read_text())
    version, build = versions(release, os.environ["BUILD_NUMBER"], os.environ["PREVIOUS_BUILD_NUMBER"])
    temp = Path(os.environ["RUNNER_TEMP"])
    if args.command == "preflight":
        preflight(os.environ, args.upload, args.method)
        with open(os.environ["GITHUB_ENV"], "a") as env:
            env.write(f"RELEASE_VERSION={version}\nRELEASE_BUILD={build}\n")
        print("Signing prerequisites present; Apple eligibility and device acceptance remain unverified.")
    elif args.command == "profile":
        profile = plistlib.loads((temp / "profile.plist").read_bytes())
        metadata = validate_profile(profile, os.environ["APPLE_TEAM_ID"], args.method)
        metadata["certificate"] = certificate_metadata(temp / "signing.p12", profile)
        (temp / "signing-metadata.json").write_text(json.dumps(metadata, indent=2))
        identity = "Apple Development" if args.method == "debugging" else "Apple Distribution"
        options = {"method": args.method, "destination": "export", "teamID": os.environ["APPLE_TEAM_ID"],
                   "signingStyle": "manual", "signingCertificate": identity,
                   "provisioningProfiles": {BUNDLE: profile["UUID"]}, "manageAppVersionAndBuildNumber": False}
        (temp / "ExportOptions.plist").write_bytes(plistlib.dumps(options))
        with open(os.environ["GITHUB_ENV"], "a") as env:
            env.write(f"PROFILE_UUID={profile['UUID']}\nSIGNING_IDENTITY={identity}\n")
    else:
        ipas = list((temp / "CrierExport").glob("*.ipa"))
        if len(ipas) != 1:
            raise ValueError("Expected exactly one signed IPA")
        endpoint = json.loads((root / "crier/connection-service.json").read_text())["url"]
        result = manifest(ipas[0], version, build, os.environ["GITHUB_SHA"], endpoint,
                          json.loads((temp / "signing-metadata.json").read_text()))
        (temp / "CrierExport/release-manifest.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        # Subprocess stderr may contain sensitive certificate/container details.
        raise SystemExit("Release blocked: certificate command failed" if isinstance(error, subprocess.CalledProcessError) else str(error))

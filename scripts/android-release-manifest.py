"""Verify signed Android outputs and record only public signing provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def certificate_sha256(output: str) -> str:
    matches = re.findall(r"(?:SHA256:|certificate SHA-256 digest:)\s*([0-9A-Fa-f:]+)", output)
    normalized = {value.replace(":", "").upper() for value in matches}
    if len(normalized) != 1 or len(next(iter(normalized), "")) != 64:
        raise ValueError("Expected exactly one SHA-256 signing certificate")
    return normalized.pop()


def run(*arguments: str) -> str:
    result = subprocess.run(arguments, text=True, capture_output=True)
    if result.returncode:
        # Tool output can include environment-specific sensitive paths; never echo it.
        raise RuntimeError(f"{Path(arguments[0]).name} verification failed")
    return result.stdout + result.stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--aab", type=Path, required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--keytool", default="keytool")
    parser.add_argument("--jarsigner", default="jarsigner")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    apk_cert = certificate_sha256(run(args.apksigner, "verify", "--verbose", "--print-certs", str(args.apk)))
    store_cert = certificate_sha256(run(args.keytool, "-J-Duser.language=en", "-list", "-v", "-keystore",
        os.environ["ANDROID_KEYSTORE_PATH"], "-storepass:env", "ANDROID_KEYSTORE_PASSWORD",
        "-alias", os.environ["ANDROID_KEY_ALIAS"]))
    bundle_verification = run(args.jarsigner, "-J-Duser.language=en", "-verify", str(args.aab))
    if "jar verified." not in bundle_verification:
        raise ValueError("AAB has no verified JAR signature")
    aab_cert = certificate_sha256(run(args.keytool, "-J-Duser.language=en", "-printcert", "-jarfile", str(args.aab)))
    if apk_cert != store_cert or aab_cert != store_cert:
        raise ValueError("APK, AAB and injected keystore certificates differ")
    artifacts = [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "bytes": path.stat().st_size} for path in (args.apk, args.aab)]
    manifest = {
        "application_id": "com.sentinel.crier",
        "release_channel": "candidate",
        "physical_device_acceptance": "deferred_by_owner",
        "version_name": os.environ["ANDROID_VERSION_NAME"],
        "version_code": int(os.environ["ANDROID_VERSION_CODE"]),
        "previous_version_code": int(os.environ["ANDROID_PREVIOUS_VERSION_CODE"]),
        "commit": os.environ.get("GITHUB_SHA", "local-unpublished"),
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
        "certificate_sha256": apk_cert,
        "signing_provenance": "Operator-provided Android signing identity; not Play App Signing or independent publisher certification",
        "apk_signature_verified": True,
        "aab_jar_signature_verified": True,
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

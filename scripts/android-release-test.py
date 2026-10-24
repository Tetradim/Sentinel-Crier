"""Offline regression checks for public certificate evidence parsing."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("release_manifest", Path(__file__).with_name("android-release-manifest.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CertificateEvidenceTest(unittest.TestCase):
    def test_apk_and_keystore_fingerprints_normalize_to_same_identity(self):
        digest = "ab" * 32
        self.assertEqual(module.certificate_sha256("Signer #1 certificate SHA-256 digest: " + digest),
                         module.certificate_sha256("SHA256: " + ":".join(["AB"] * 32)))

    def test_missing_truncated_or_multiple_signers_fail_closed(self):
        for output in ("unsigned", "SHA256: AB:CD", "SHA256: " + "a" * 64 + "\nSHA256: " + "b" * 64):
            with self.subTest(output=output), self.assertRaises(ValueError):
                module.certificate_sha256(output)


if __name__ == "__main__":
    unittest.main()

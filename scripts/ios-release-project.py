"""Generate local/native project defaults from the shared release source.

Signed CI overrides build number with the explicitly validated workflow input.
The default minimum is for simulator builds, never a claim about prior uploads.
"""
import json
from pathlib import Path
import re


def generate(root):
    release = json.loads((root / "release.json").read_text())
    version = release["version"]
    build = int(release["ios"]["minimum_build_number"])
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or build < 1:
        raise ValueError("Invalid release defaults")
    (root / "ios/ReleaseVersion.xcconfig").write_text(
        "// Generated from release.json by scripts/ios-release-project.py.\n"
        f"MARKETING_VERSION = {version}\nCURRENT_PROJECT_VERSION = {build}\n")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1])

#!/bin/bash
set -euo pipefail
# GitHub images can change their default Xcode. Select the newest stable install.
XCODE_APP=$(python3 - <<'PY'
import pathlib, re
apps = []
for app in pathlib.Path('/Applications').glob('Xcode_*.app'):
    match = re.fullmatch(r'Xcode_(\d+(?:\.\d+)*).app', app.name)
    if match:
        apps.append((tuple(map(int, match[1].split('.'))), app))
if not apps:
    raise SystemExit('No versioned stable Xcode installation available')
print(max(apps)[1])
PY
)
sudo xcode-select -s "$XCODE_APP/Contents/Developer"
xcodebuild -version
xcodebuild -showsdks

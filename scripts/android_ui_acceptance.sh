#!/usr/bin/env bash
set -euo pipefail

adb shell settings put system font_scale 1.3
adb logcat -G 16M
adb logcat -c
trap 'adb logcat -d -s CrierScreenshots:I > "$RUNNER_TEMP/crier-ui-screenshots.log"' EXIT
gradle -p android --no-daemon :app:connectedDebugAndroidTest

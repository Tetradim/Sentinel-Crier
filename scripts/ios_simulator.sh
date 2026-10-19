#!/bin/bash
set -euo pipefail
if ! xcrun simctl list runtimes -j | python3 -c 'import sys,json; sys.exit(0 if any(x.get("isAvailable") and "iOS" in x["name"] for x in json.load(sys.stdin)["runtimes"]) else 1)'; then
  xcodebuild -downloadPlatform iOS
fi
SIMULATOR_ID=$(python3 - <<'PY'
import json, subprocess
def listing(kind):
    return json.loads(subprocess.check_output(['xcrun', 'simctl', 'list', kind, '-j']))
runtimes = [r for r in listing('runtimes')['runtimes'] if r.get('isAvailable') and 'iOS' in r['name']]
if not runtimes:
    raise SystemExit('No usable iOS runtime')
runtime = max(runtimes, key=lambda r: tuple(map(int, r['version'].split('.'))))
devices = listing('devices')['devices'].get(runtime['identifier'], [])
phones = [d for d in devices if d.get('isAvailable') and d['name'].startswith('iPhone')]
if phones:
    print(phones[0]['udid'])
else:
    types = [d for d in listing('devicetypes')['devicetypes'] if d['name'].startswith('iPhone')]
    if not types:
        raise SystemExit('No iPhone simulator device type')
    print(subprocess.check_output(['xcrun', 'simctl', 'create', 'Crier CI', types[-1]['identifier'], runtime['identifier']], text=True).strip())
PY
)
echo "IOS_SIMULATOR_ID=$SIMULATOR_ID" >> "$GITHUB_ENV"
xcrun simctl boot "$SIMULATOR_ID" || true
xcrun simctl bootstatus "$SIMULATOR_ID" -b

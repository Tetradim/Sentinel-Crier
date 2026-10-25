# H.4 Windows presence implementation plan

Execute under the approved H plan directly on main. Use test-first regressions and the current checkout.

- [x] Add failing portable tests for default-off/corrupt preferences, explicit startup registration, packaged executable validation, tray readiness/failure, queued actions and shutdown.
- [x] Implement `desktop_presence.py` for preferences, current-user startup registration and an injected tray lifecycle. Add `windows_tray.py` using pystray and generated Pillow imagery, with fixed queued actions only.
- [x] Add opt-in controls to Start here, safe close/hide/show behavior and `--startup` handling. Keep all launches disconnected and entries paused. Test hidden-window wiring and existing quit behavior.
- [x] Add pinned Windows tray dependencies to desktop packaging; extend packaged offline smoke tests and installer uninstall acceptance to cover tray and startup cleanup.
- [x] Include the exact installed tray source, upstream build files, GPL/LGPL texts and Pillow/six notices in Windows packages; verify version/missing-source refusals and the archived bundle manifest.
- [x] Run focused/full Python and Windows CI, preserve source-bound evidence, update H.4 status and commit/push. H.5 policy design and physical/signing/provider activation remain separate.

## Verification

Source `7f8efe3` passed **867 local Python tests/one optional SDK skip** and **62 focused lifecycle/UI/installer tests**. The final source-bound CI matrix passed Windows Python 3.11 **867/one skip** and Linux Python 3.11/3.12 **837/31 platform/optional skips each**. The Windows release environment passed **798/three optional skips** before packaging.

The packaged executable's native notification-area icon became ready and stopped successfully, with zero network calls. Real installer checks confirmed default-off startup, explicit current-user opt-in, upgrade preservation and uninstall cleanup while retaining synthetic journals/DPAPI credentials. See the [source-bound evidence](../../acceptance/2026-10-25/windows-presence/source-evidence.json), [packaged smoke report](../../acceptance/2026-10-25/windows-presence/windows-packaged-smoke.json), and [installer report](../../acceptance/2026-10-25/windows-presence/windows-installer-acceptance.json).

H.4 scoped source and hosted-runner verification are complete. Real Windows sign-in and physical Explorer/taskbar interaction remain untested. No real orders/messages, service deployment or signing occurred. H.5 deliberate execution-policy design remains implementation work.

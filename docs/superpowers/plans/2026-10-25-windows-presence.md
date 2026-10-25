# H.4 Windows presence implementation plan

Execute under the approved H plan directly on main. Use test-first regressions and the current checkout.

- [ ] Add failing portable tests for default-off/corrupt preferences, explicit startup registration, packaged executable validation, tray readiness/failure, queued actions and shutdown.
- [ ] Implement `desktop_presence.py` for preferences, current-user startup registration and an injected tray lifecycle. Add `windows_tray.py` using pystray and generated Pillow imagery, with fixed queued actions only.
- [ ] Add opt-in controls to Start here, safe close/hide/show behavior and `--startup` handling. Keep all launches disconnected and entries paused. Test hidden-window wiring and existing quit behavior.
- [ ] Add pinned Windows tray dependencies to desktop packaging; extend packaged offline smoke tests and installer uninstall acceptance to cover tray and startup cleanup.
- [ ] Run focused/full Python and Windows CI, preserve source-bound evidence, update H.4 status and commit/push. H.5 policy design and physical/signing/provider activation remain separate.

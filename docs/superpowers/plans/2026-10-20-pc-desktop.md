# PC desktop implementation plan

**Goal:** Deliver a launchable Windows app using the already approved iOS/PC intent protocol.

**Architecture:** Native Tk desktop controls, a background asyncio runtime, and the existing IntentDevice/IntentEngine. Pairing and broker credentials remain protected with Windows DPAPI. HTTPS relay pairing is unchanged; this does not provision a public relay. The desktop starts disconnected and every connection starts entries paused. One process owns the desktop journal.

**Tech stack:** Python, Tk/ttk, asyncio, existing httpx/SQLite engine, PyInstaller Windows executable.

- [ ] Test desktop account discovery, pairing validation, immutable account/channel binding, protected settings and paused connection. Use a fake account HTTP transport and fake broker; never place orders.
- [ ] Add `crier/desktop_runtime.py`: serialized lifecycle, verify account before activation, encrypted configuration, nonblocking status/commands, stop receiver/publisher then await executor before closing broker.
- [ ] Add `crier/desktop.py`: connection form, masked keys, pairing paste, visible environment/account/role, settings, Follow/Pause, tracked orders and host commands. Keep all network and broker work off Tk's main thread.
- [ ] Add `desktop/launch.py`, PowerShell build script and Windows CI; produce a portable directory ZIP with Python bundled and an offline executable smoke-test option.
- [ ] Run desktop tests/full suite, instantiate UI without broker calls, build executable, run bundled smoke test, document iOS→PC setup and push directly to main.

Acceptance: the Windows app launches without Python installed, accepts the same follower pairing as iOS, shows actual broker order status via the shared engine, and never sends an order merely by opening or connecting. No real-account test is performed by development scripts.

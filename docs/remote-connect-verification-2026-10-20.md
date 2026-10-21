# Remote connection verification — 2026-10-20

Implementation commit: `3afba82` on main.

- **296 Python tests passed** locally and in backend CI, with the existing
  Starlette/httpx deprecation warning. New checks cover invitation expiry/replay,
  independent receiver credentials, revocation, rate limiting, environment mismatch
  without consumption, provisional pairing protection, join-time cursor boundaries,
  standalone relay behavior and bounded request bodies.
- [Windows build](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39537944166)
  passed tests, portable packaging, the offline executable smoke test and artifact
  upload. A local rebuild also passed, including the bundled shared URL resource.
- [iOS compile](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39537944162)
  passed. [Native simulator tests](https://github.com/Tetradim/Sentinel-Crier/actions/runs/39537944241)
  passed **53 tests**, including four new invitation/origin parsing tests.
- Independent code review identified two pairing-state defects; both were fixed and
  regression-tested before the verified commit.

No hosting account, subscription, public server or configured production origin was
created. `connection-service.json` remains deliberately empty. The Render Blueprint
and [deployment instructions](remote-connect-setup.md) are ready for operator setup;
provider-side deployment validation, proxy/client-IP behavior and cross-network
physical-device paper testing remain unverified. The relay template uses a paid
service and persistent disk; the operator must review and approve provider charges.

No brokerage orders or Discord posts were made during this implementation.

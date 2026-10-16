# Cloud hosting: macOS build runners vs live brokerage server

Crier has two separate hosting needs:

1. **Compile and test the native iPhone app.** Requires macOS/Xcode.
2. **Run a continuously available brokerage/order-monitoring backend.**
   Does **not** require macOS. Prefer a small secured Linux VM and do not
   run customer live trading on an ephemeral CI runner.

## Free or low-cost approaches researched (October 2026)

- **GitHub Actions macOS:** For public repos, standard hosted runners are
  free. The repository already has macOS Xcode build CI. These runners are
  short-lived, so they cannot be the always-on trading/order backend. For
  private repos, GitHub minutes and billing limits apply.
  https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- **Xcode Cloud:** 25 compute hours per month included with Apple Developer
  Program membership; not an always-on Mac server, and the membership is
  not free. https://developer.apple.com/xcode-cloud/
- **MacStadium dedicated Mac:** Paid (published Mac mini prices start at
  $109/month); no free individual Mac trial.
  https://macstadium.com/pricing
- **AWS EC2 Mac:** Paid Dedicated Host with a 24-hour minimum host allocation.
  https://aws.amazon.com/ec2/instance-types/mac/faqs/
- **Oracle Cloud Always Free (Linux):** Eligible Ubuntu Linux compute can
  host a development Crier backend with no monthly VM charge while within
  Always Free limits. Resource supply varies by region; account verification
  and capacity are not guaranteed. This is not an assurance of zero total
  costs or production uptime.
  https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

**Recommendation:** Keep GitHub Actions macOS for building the iOS app;
choose an Oracle Always Free Linux VM *for initial backend bring-up* if
available. Before live customer trading, evaluate paid production
infrastructure, data durability, backups, availability, monitoring, and
regulatory/security obligations. Do not deploy customer order execution to
unmonitored, best-effort free hosting.

## Current secure cloud development endpoint

`crier.cloud_gateway` is a **read-only, fail-closed bring-up service**.
It returns service liveness, authenticated broker connection readiness, and
explicitly unavailable account/positions/options/orders responses. It does
not handle credentials, customer OAuth, account balances, order creation,
or confirmed broker fills. No paper/demo order mode exists.

Required environment setting:
`CRIER_CLOUD_OPERATOR_TOKEN` = random 48+ character secret. This is a
**single-operator bring-up token, not customer authentication**. Never place
it in mobile code, a GitHub commit, logs, or app settings distributed to users.

Generate locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Provision as a service-manager environment secret or secret-store integration.

On a provisioned Ubuntu VM, install Python 3.11+, clone repo in a dedicated
unprivileged service account, and run:

```sh
python -m venv .venv
.venv/bin/pip install -e .
export CRIER_CLOUD_OPERATOR_TOKEN='<generated secret from your secret manager>'
.venv/bin/python -m crier.cloud_gateway
```

The listener intentionally binds **127.0.0.1:8876**. Test locally with
an Authorization bearer header. Unauthenticated `GET /health` only means
the process is alive, never that real trading is available.

For network access, put an authenticated/controlled HTTPS reverse proxy
in front of the loopback listener. Configure an owned DNS hostname and
TLS certificates, restrict ports to 443, rate limit ingress, and do not
expose the raw service directly. A template is provided in
`ops/Caddyfile.cloud.example`.

**Do not copy/paste the development operator bearer token into a customer
app.** Per-customer login, expiring user sessions, OAuth 2.0/PCKE state
validation, encrypted per-user broker token storage, and tenant isolation
must be completed before exposing any customer account endpoint.

## Broker access dependency

Webull's **Connect API** is the appropriate integration track for a
third-party application connecting customers' Webull accounts; it requires
application approval and OAuth client credentials. For individuals trading
their own account Webull offers a separate Trading API.

Webull's documented production OAuth API host:
`us-oauth-open-api.webull.com`; do not reuse older unofficial Python
`webull` account login clients.

See: https://developer.webull.com/apis/docs/connect-api/about-connect-api/

No application registration, VM allocation, DNS changes, broker credential
provisioning, or live trade has been made by this repository change.

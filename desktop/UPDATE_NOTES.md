Crier 0.5.0 adds an opt-in Account ID bank to the Windows Alpaca receiver. Several hosts can share one destination account with separate trade IDs, owned positions and reusable stock/option pools in units, dollars or percentage of destination equity. Exits reserve only the issuing host's units. Completed empty IDs archive; history and duplicate protection remain.

Supported candidate update source: 0.4.0. Existing routes remain exclusive until explicit bank setup. Setup drains all routes and refuses unresolved legacy orders or open legacy Crier lots. New pools start at zero. Configure pools, reconnect, inspect settings and explicitly enable orders. Managed execution requires limit pricing and fresh supported USD account evidence.

Preserve the entire profile, including account-bank.sqlite3, connections.sqlite3 and all route journals. Timeouts retain reservations; partial fills retain ownership. Updates snapshot the profile after workers drain. Stopping Crier does not cancel broker orders. Startup stays disconnected with entries paused. Never delete recovery evidence to bypass a block.

Native shared-account receivers, Webull/Tradier execution, cross-installation coordination, physical broker-UI acceptance and platform signing remain separate work. See docs/account-id-bank.md for coverage and setup.

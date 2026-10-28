Crier 0.3.1 adds a dismissible Windows update notice checked once at startup, persistent connection status, a read-only connection test, and a Support dialog with version details and sanitized export. Manual update checking remains available. Startup checks never download or install updates, and hidden tray startup remains hidden.

Supported update source: 0.3.0. Profile and trade protocol generation remain 1; there is no database migration. Existing journals, pairing, credentials and settings are retained.

Test my connection verifies the selected Alpaca account/environment and authenticated relay connectivity without orders or Discord messages. It does not prove peer trade execution or Discord delivery. Account reads and relay responses have bounded deadlines and response sizes.

Crier drains broker work and closes before installation. Existing broker orders remain active. Start manually afterward, verify the account and unresolved orders, and reconnect deliberately. Preserve the original profile and protected Recovery snapshot; restore only into a new private folder for inspection. Unsupported profile generations and downgrades are refused.

Webull Connect activation, Apple signing, physical cross-network acceptance and optional Microsoft publisher signing remain separate prerequisites.

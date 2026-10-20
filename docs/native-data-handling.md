# Native app data handling

This describes the current standalone Alpaca iPhone path. Operators distributing
the app must supply their contact details and review their App Store privacy
answers against the actual build and any added services.

## On the phone

Alpaca keys and the Discord webhook are stored in device-only Keychain entries.
Paper and live Alpaca keys are separate. The protected local journal contains
account identifiers, submitted tickets, broker order responses, fill activity,
and Discord delivery status. UI preferences use local UserDefaults. The app does
not include advertising, analytics, or tracking SDKs.

An optional receiver pairing is stored in device-only Keychain. The separate
protected mirror journal stores source fills, account binding, pairing fingerprints
and delivery states. It does not contain the pairing token.

## Network destinations

Connecting sends authenticated requests directly to Alpaca. Confirming an order
sends the exact reviewed ticket to the selected paper or live endpoint. While
the app is active, refreshes retrieve account, position, order and fill data.

Saving a Discord webhook enables publishing newly observed fills from the
connected account, including trades made outside Crier. Messages include the
instrument, side, quantity, execution price, broker timestamp and paper/live
label. Public messages omit account IDs, broker order IDs and credentials.
Everyone with access to the destination channel can read these messages.

Saving a Mirror pairing enables sending new supported fills to the customer's
chosen HTTPS receiver, independently of Discord. Messages include the exact
instrument, buy/sell intent, execution quantity/price/time, paper/live environment
and a hashed event identity. They omit raw account IDs, broker order IDs and
brokerage credentials. The receiver operator can read and retain these events
and, when Follow is enabled, execute matching orders in their own account.
Removing the pairing stops subsequent sharing but does not delete the receiver's
history or cancel orders already submitted there. Pending fills are tied to their
original pairing and are not sent to a different newly paired receiver.

The first successful connection baselines existing history without posting it.
Disconnecting stops account monitoring. Removing a webhook stops subsequent
delivery; it does not delete messages already posted to Discord or erase pending
local fills. Configuring another webhook can deliver those pending fills there.

## Retention and recovery

Removing credentials does not erase the local journal. Its saved submission IDs
and delivery states prevent duplicates after restart. Preserve the journal during
recovery: deleting it removes that protection. Discord and Alpaca retain their
own records under their respective policies. The optional Python monitor is a
separate installation with its own storage and configuration.

The bundled privacy manifest declares settings-storage API usage; it is not a
substitute for the distributor's privacy policy or App Store privacy disclosures.

## Submission-time intent relay

Intent pairing is separate from legacy fill sharing. Its HTTPS relay receives order instructions (contract, action, requested quantity/price, paper/live environment, timestamps and random trade/event IDs) when the host submits or changes an order, before broker confirmation. Broker API keys remain on each execution device. The relay operator retains those instructions and pairing-token hashes. Host and follower tokens have separate publish/read scopes. Each device retains a durable journal of received revisions, outgoing commands, its own broker orders and actual fills; do not delete it to resolve an unknown submission. Revocation stops future delivery but cannot undo an already submitted order. Physical device release/privacy disclosures must cover the deployed relay operator and retention policy.

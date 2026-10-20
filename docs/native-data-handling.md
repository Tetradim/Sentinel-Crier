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

## Network destinations

Connecting sends authenticated requests directly to Alpaca. Confirming an order
sends the exact reviewed ticket to the selected paper or live endpoint. While
the app is active, refreshes retrieve account, position, order and fill data.

Saving a Discord webhook enables publishing newly observed fills from the
connected account, including trades made outside Crier. Messages include the
instrument, side, quantity, execution price, broker timestamp and paper/live
label. Public messages omit account IDs, broker order IDs and credentials.
Everyone with access to the destination channel can read these messages.

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

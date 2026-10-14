# Webull sample-data collection guide

We are developing against **Webull** first. Realistic, **redacted** examples are useful for parser fixtures, but never send account credentials or unredacted screenshots.

## Helpful examples

1. A **completed options buy** confirmation, including the visible labels for symbol, expiration, call/put, strike, quantity and average execution price.
2. A **completed options sell** confirmation.
3. An **order preview** and a **submitted-but-not-filled** order (negative test cases).
4. A **partial fill** and a subsequently completed fill, if available.
5. Two separate executions of the same contract, if available, to test duplicate detection.

For each example, note whether it came from the **iOS Webull app**, a Webull export, or an official Webull API response. A screen layout is not interchangeable with an API event schema.

## Redact before sharing

Remove account numbers, names, email addresses, phone numbers, balances, positions unrelated to the example, order IDs, API keys, access tokens, QR codes, and other personal details. Replace real order identifiers with distinct synthetic IDs (e.g. ORDER_A and ORDER_B) if the distinction matters. Do not share a Discord webhook URL. Do not share passwords, MFA codes or session cookies.

If redaction removes context, supply a **typed transcription** of only the relevant field labels and values. Include whether the order was filled, partially filled, pending, cancelled, or rejected. Do not fabricate a completed fill from an order preview.

## Validation criteria

- Each fixture must identify its source, timestamp basis, and expected classification.
- Preview, pending, cancelled, rejected, ambiguous and partial-fill fixtures must never automatically publish.
- The same visible screen appearing across frames must not create repeated alerts.
- Two distinct executions with identical contract, quantity and price must remain distinguishable through broker order/execution evidence.
- Screen OCR observations remain pending review and must never masquerade as broker-verified fills.

## Technical limits

ReplayKit broadcasting requires the customer to initiate screen sharing. It cannot monitor Webull silently when the Webull app is not visible. Official API coverage for the customer's account must be independently confirmed before unattended monitoring can be promised.

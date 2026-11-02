import Foundation

/// Pure, bounded explanations. Only fixed messages are rendered; no broker or storage access.
enum DecisionSummary {
    private static let messages: [String: String] = [
        "journaled": "The instruction was saved on this device.",
        "received": "The instruction reached this device.",
        "relay_ack": "The relay acknowledged the instruction; broker execution is not confirmed.",
        "relay_started": "Sending the instruction to the relay was started; delivery is not confirmed.",
        "relay_rejected": "The relay rejected the instruction; broker execution is not confirmed.",
        "started": "A broker submission was started; the outcome is not confirmed.",
        "returned": "The broker submission call returned; a fill is not confirmed.",
        "not_submitted": "This attempt was not submitted to the broker.",
        "rejected": "This submission was refused; a fill is not established by this record.",
        "unknown": "The broker outcome is unknown. Reconciliation is required before new work.",
        "cancel_requested": "Cancellation was requested; cancellation is not confirmed.",
        "canceled": "The broker reports the order canceled; earlier fills may remain.",
        "partial": "The broker reports a partial fill; the full order is not confirmed filled.",
        "filled": "The broker reports the order filled.",
        "active": "The broker reports an active order; a full fill is not confirmed.",
        "expired": "The broker reports the order expired; earlier fills may remain.",
        "broker_evidence": "Broker evidence was refreshed; the recorded outcome is not confirmed.",
        "skipped": "The entry was skipped by local checks.",
        "deferred": "The entry was deferred; no new submission is confirmed.",
        "clock": "The entry was deferred because the device clock needs checking.",
        "future": "The entry is waiting for its recorded start time.",
        "paused": "The entry was skipped because new entries were paused.",
        "limit": "The entry was skipped because a local quantity or age limit was reached.",
        "entry_expired": "The entry was skipped because its instruction expired.",
        "invalidated": "The entry remainder was invalidated; any recorded fills are retained.",
        "complete": "Local instruction processing completed; a fill is not confirmed.",
        "execution_started": "Local execution checks started; submission is not confirmed.",
        "other": "Additional evidence was recorded; its meaning is unavailable.",
        "empty": "No decision evidence is recorded yet."
    ]
    private static let stages: [String: String] = [
        "sender_instruction_journaled": "journaled",
        "sender": "journaled",
        "instruction_stored": "journaled",
        "receiver_instruction_stored": "journaled",
        "receiver_instruction_arrived": "received",
        "receiver": "received",
        "relay_publish_acknowledged": "relay_ack",
        "relay_ack": "relay_ack",
        "relay_accepted": "relay_ack",
        "relay_publish_started": "relay_started",
        "relay_publish_rejected": "relay_rejected",
        "relay_rejected": "relay_rejected",
        "broker_submit_started": "started",
        "submit_attempt": "started",
        "order_dispatch": "started",
        "broker_submit_returned": "returned",
        "broker_response": "returned",
        "broker_not_submitted": "not_submitted",
        "order_not_submitted": "not_submitted",
        "broker_submit_superseded": "not_submitted",
        "broker_submit_rejected": "rejected",
        "broker_rejected": "rejected",
        "broker_lookup_unknown": "unknown",
        "broker_lookup_unusable": "unknown",
        "execution_error": "unknown",
        "cancel_uncertain": "unknown",
        "reconciliation_wait": "unknown",
        "reconciliation_error": "unknown",
        "execution_pending": "unknown",
        "cancel_requested": "cancel_requested",
        "cancel_dispatch": "cancel_requested",
        "entry_invalidated": "invalidated",
        "execution_complete": "complete",
        "execution_started": "execution_started"
    ]
    private static let statuses: [String: String] = [
        "new": "active",
        "accepted": "active",
        "pending_new": "active",
        "accepted_for_bidding": "active",
        "pending_replace": "active",
        "partially_filled": "partial",
        "filled": "filled",
        "canceled": "canceled",
        "pending_cancel": "cancel_requested",
        "rejected": "rejected",
        "expired": "expired",
        "unknown": "unknown",
        "submit_unknown": "unknown",
        "cancel_unknown": "unknown"
    ]
    private static let states: [String: String] = [
        "reconcile_required": "unknown",
        "waiting_for_reconciliation": "unknown",
        "manual_reconcile": "unknown",
        "cancel_pending": "cancel_requested",
        "rejected": "rejected",
        "skipped": "skipped",
        "superseded": "not_submitted",
        "invalidated": "invalidated",
        "settled": "complete",
        "submitted": "returned",
        "waiting_for_clock": "clock",
        "waiting_for_start": "future"
    ]
    private static let reasons: [String: String] = [
        "clock_changed": "clock",
        "future_created_at": "future",
        "prior_order_evidence_unavailable": "unknown",
        "entries_paused": "paused",
        "expired": "entry_expired",
        "max_quantity": "limit",
        "age_or_revision_limit": "limit",
        "too_old": "limit"
    ]
    private static func details(_ value: Any?) -> [String: Any] {
        if let object = value as? [String: Any] { return object }
        if let text = value as? String, text.utf8.count <= 16384, let data = text.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { return object }
        return [:]
    }
    private static func lookup(_ table: [String: String], _ value: Any?, _ fallback: String) -> String {
        guard let value = value as? String else { return fallback }
        return table[value] ?? fallback
    }
    private static func message(_ row: [String: Any]) -> String {
        let stage = row["stage"] as? String ?? ""
        let d = details(row["details"])
        let key: String
        switch stage {
        case "broker_reconciled", "reconciled", "order_state": key = lookup(statuses, d["status"], "broker_evidence")
        case "execution_decision": key = lookup(states, d["state"], "other")
        case "entry_deferred", "execution_deferred", "entry_skipped": key = lookup(reasons, d["reason"], stage == "entry_skipped" ? "skipped" : "deferred")
        default: key = lookup(stages, stage, "other")
        }
        return messages[key]!
    }
    static func describe(_ timeline: [[String: Any]], limit: Int = 8) -> [String] {
        guard !timeline.isEmpty else { return [messages["empty"]!] }
        let count = max(1, min(20, limit))
        var result: [String] = []
        for row in timeline {
            let text = message(row)
            if result.last != text {
                result.append(text)
                if result.count > count { result.removeFirst() }
            }
        }
        return result
    }
    /// Free text from older journals cannot prove a status or fill.
    static func fromTimeline(_ timeline: [DiagnosticStep], limit: Int = 8) -> [String] {
        describe(timeline.map { ["stage": $0.stage, "details": details($0.detail)] }, limit: limit)
    }
}

package com.sentinel.crier
import org.json.JSONArray
import org.json.JSONObject

/** Pure, bounded explanations of existing evidence; never contacts the broker. */
object DecisionSummary {
 private val messages=mapOf(
  "journaled" to "The instruction was saved on this device.",
  "received" to "The instruction reached this device.",
  "relay_ack" to "The relay acknowledged the instruction; broker execution is not confirmed.",
  "relay_started" to "Sending the instruction to the relay was started; delivery is not confirmed.",
  "relay_rejected" to "The relay rejected the instruction; broker execution is not confirmed.",
  "started" to "A broker submission was started; the outcome is not confirmed.",
  "returned" to "The broker submission call returned; a fill is not confirmed.",
  "not_submitted" to "This attempt was not submitted to the broker.",
  "rejected" to "This submission was refused; a fill is not established by this record.",
  "unknown" to "The broker outcome is unknown. Reconciliation is required before new work.",
  "cancel_requested" to "Cancellation was requested; cancellation is not confirmed.",
  "canceled" to "The broker reports the order canceled; earlier fills may remain.",
  "partial" to "The broker reports a partial fill; the full order is not confirmed filled.",
  "filled" to "The broker reports the order filled.",
  "active" to "The broker reports an active order; a full fill is not confirmed.",
  "expired" to "The broker reports the order expired; earlier fills may remain.",
  "broker_evidence" to "Broker evidence was refreshed; the recorded outcome is not confirmed.",
  "skipped" to "The entry was skipped by local checks.",
  "deferred" to "The entry was deferred; no new submission is confirmed.",
  "clock" to "The entry was deferred because the device clock needs checking.",
  "future" to "The entry is waiting for its recorded start time.",
  "paused" to "The entry was skipped because new entries were paused.",
  "limit" to "The entry was skipped because a local quantity or age limit was reached.",
  "entry_expired" to "The entry was skipped because its instruction expired.",
  "invalidated" to "The entry remainder was invalidated; any recorded fills are retained.",
  "complete" to "Local instruction processing completed; a fill is not confirmed.",
  "execution_started" to "Local execution checks started; submission is not confirmed.",
  "other" to "Additional evidence was recorded; its meaning is unavailable.",
  "empty" to "No decision evidence is recorded yet."
 )
 private val stages=mapOf(
  "sender_instruction_journaled" to "journaled",
  "sender" to "journaled",
  "instruction_stored" to "journaled",
  "receiver_instruction_stored" to "journaled",
  "receiver_instruction_arrived" to "received",
  "receiver" to "received",
  "relay_publish_acknowledged" to "relay_ack",
  "relay_ack" to "relay_ack",
  "relay_accepted" to "relay_ack",
  "relay_publish_started" to "relay_started",
  "relay_publish_rejected" to "relay_rejected",
  "relay_rejected" to "relay_rejected",
  "broker_submit_started" to "started",
  "submit_attempt" to "started",
  "order_dispatch" to "started",
  "broker_submit_returned" to "returned",
  "broker_response" to "returned",
  "broker_not_submitted" to "not_submitted",
  "order_not_submitted" to "not_submitted",
  "broker_submit_superseded" to "not_submitted",
  "broker_submit_rejected" to "rejected",
  "broker_rejected" to "rejected",
  "broker_lookup_unknown" to "unknown",
  "broker_lookup_unusable" to "unknown",
  "execution_error" to "unknown",
  "cancel_uncertain" to "unknown",
  "reconciliation_wait" to "unknown",
  "reconciliation_error" to "unknown",
  "execution_pending" to "unknown",
  "cancel_requested" to "cancel_requested",
  "cancel_dispatch" to "cancel_requested",
  "entry_invalidated" to "invalidated",
  "execution_complete" to "complete",
  "execution_started" to "execution_started"
 )
 private val statuses=mapOf(
  "new" to "active",
  "accepted" to "active",
  "pending_new" to "active",
  "accepted_for_bidding" to "active",
  "pending_replace" to "active",
  "partially_filled" to "partial",
  "filled" to "filled",
  "canceled" to "canceled",
  "pending_cancel" to "cancel_requested",
  "rejected" to "rejected",
  "expired" to "expired",
  "unknown" to "unknown",
  "submit_unknown" to "unknown",
  "cancel_unknown" to "unknown"
 )
 private val states=mapOf(
  "reconcile_required" to "unknown",
  "waiting_for_reconciliation" to "unknown",
  "manual_reconcile" to "unknown",
  "cancel_pending" to "cancel_requested",
  "rejected" to "rejected",
  "skipped" to "skipped",
  "superseded" to "not_submitted",
  "invalidated" to "invalidated",
  "settled" to "complete",
  "submitted" to "returned",
  "waiting_for_clock" to "clock",
  "waiting_for_start" to "future"
 )
 private val reasons=mapOf(
  "clock_changed" to "clock",
  "future_created_at" to "future",
  "prior_order_evidence_unavailable" to "unknown",
  "entries_paused" to "paused",
  "expired" to "entry_expired",
  "max_quantity" to "limit",
  "age_or_revision_limit" to "limit",
  "too_old" to "limit"
 )
 private fun details(value:Any?):JSONObject = when(value) {
  is JSONObject -> value
  is String -> if(value.length<=16384) runCatching { JSONObject(value) }.getOrDefault(JSONObject()) else JSONObject()
  else -> JSONObject()
 }
 private fun lookup(table:Map<String,String>,value:Any?,fallback:String):String = if(value is String) table[value] ?: fallback else fallback
 private fun message(row:JSONObject?):String {
  val stage=row?.opt("stage"); val d=details(row?.opt("details"))
  val key=when(stage) {
   "broker_reconciled","reconciled","order_state" -> lookup(statuses,d.opt("status"),"broker_evidence")
   "execution_decision" -> lookup(states,d.opt("state"),"other")
   "entry_deferred","execution_deferred","entry_skipped" -> lookup(reasons,d.opt("reason"),if(stage=="entry_skipped") "skipped" else "deferred")
   else -> lookup(stages,stage,"other")
  }
  return messages.getValue(key)
 }
 fun describe(timeline:JSONArray,limit:Int=8):List<String> {
  if(timeline.length()==0) return listOf(messages.getValue("empty"))
  val count=limit.coerceIn(1,20); val result=mutableListOf<String>()
  for(i in 0 until timeline.length()) {
   val text=message(timeline.optJSONObject(i))
   if(result.lastOrNull()!=text) { result.add(text); if(result.size>count) result.removeAt(0) }
  }
  return result
 }
 /** Adapt structured detail and exact allowlisted status/reason enums from Journal. */
 fun fromTimeline(timeline:JSONArray,limit:Int=8):List<String> {
  val rows=JSONArray()
  for(i in 0 until timeline.length()) {
   val row=timeline.optJSONObject(i)
   val stage=row?.opt("stage"); val raw=row?.opt("detail"); var d=details(raw)
   if(stage=="order_state" && raw is String && statuses.containsKey(raw)) d=JSONObject().put("status",raw)
   if(stage in setOf("entry_deferred","execution_deferred","entry_skipped") && raw is String && reasons.containsKey(raw)) d=JSONObject().put("reason",raw)
   rows.put(JSONObject().put("stage",stage ?: JSONObject.NULL).put("details",d))
  }
  return describe(rows,limit)
 }
}

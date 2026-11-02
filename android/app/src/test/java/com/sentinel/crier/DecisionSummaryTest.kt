package com.sentinel.crier
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DecisionSummaryTest {
 @Test fun sharedFixtures() {
  val fixture=JSONObject(javaClass.classLoader!!.getResource("decision-summary.json")!!.readText())
  val cases=fixture.getJSONArray("cases")
  for(i in 0 until cases.length()) {
   val c=cases.getJSONObject(i)
   val expected=(0 until c.getJSONArray("expected").length()).map { c.getJSONArray("expected").getString(it) }
   assertEquals(c.getString("id"),expected,DecisionSummary.describe(c.getJSONArray("timeline"),c.optInt("limit",8)))
  }
 }
 @Test fun adapterReadsStructuredEvidenceAndNeverExtractsFreeText() {
  val rows=JSONArray().put(JSONObject().put("stage","broker_reconciled").put("detail","{\"status\":\"partially_filled\",\"id\":\"SECRET\"}"))
  assertEquals(listOf("The broker reports a partial fill; the full order is not confirmed filled."),DecisionSummary.fromTimeline(rows))
  val text=JSONArray().put(JSONObject().put("stage","reconciled").put("detail","status=filled id=SECRET"))
  assertEquals(listOf("Broker evidence was refreshed; the recorded outcome is not confirmed."),DecisionSummary.fromTimeline(text))
  val state=JSONArray().put(JSONObject().put("stage","order_state").put("detail","canceled"))
  assertEquals(listOf("The broker reports the order canceled; earlier fills may remain."),DecisionSummary.fromTimeline(state))
 }
 @Test fun limitsAndPrivacy() {
  val rows=JSONArray(); repeat(100) { rows.put(JSONObject().put("stage",if(it%2==0) "sender" else "receiver").put("details","SECRET")) }
  val before=rows.toString()
  for(limit in listOf(-10,0,8,Int.MAX_VALUE)) { val result=DecisionSummary.describe(rows,limit); assertTrue(result.size in 1..20); assertFalse(result.joinToString().contains("SECRET")) }
  assertEquals(before,rows.toString())
 }
 @Test fun diagnosticsIncludesReadOnlySummaryBeforeTimeline() {
  val r=JSONObject().put("event",JSONObject().put("event_id","id").put("symbol","SPY").put("action","enter")).put("timeline",JSONArray().put(JSONObject().put("stage","broker_not_submitted").put("at","now").put("detail","SECRET")))
  val text=Diagnostics.describe(r)
  assertTrue(text.contains("What happened?\nThis attempt was not submitted to the broker."))
  assertTrue(text.indexOf("What happened?")<text.indexOf("Advanced timeline"))
 }
 @Test fun adapterReadsOnlyExactJournalReasonEnums() {
  for(stage in listOf("entry_deferred","execution_deferred","entry_skipped")) {
   for(reason in listOf("clock_changed","future_created_at","entries_paused","expired","max_quantity","age_or_revision_limit")) {
    val actual=JSONArray().put(JSONObject().put("at","2026-11-02T10:00:00Z").put("stage",stage).put("detail",reason))
    val canonical=JSONArray().put(JSONObject().put("stage",stage).put("details",JSONObject().put("reason",reason)))
    assertEquals("$stage/$reason",DecisionSummary.describe(canonical),DecisionSummary.fromTimeline(actual))
   }
  }
  val unknown=JSONArray().put(JSONObject().put("stage","entry_deferred").put("detail","clock_changed PRIVATE_SECRET"))
  assertEquals(DecisionSummary.describe(JSONArray().put(JSONObject().put("stage","entry_deferred"))),DecisionSummary.fromTimeline(unknown))
 }
}

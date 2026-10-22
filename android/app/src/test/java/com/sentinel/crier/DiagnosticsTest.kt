package com.sentinel.crier
import org.junit.Assert.*
import org.junit.Test
class DiagnosticsTest {
 @Test fun missingEvidenceNeverInventsLatencyAndCsvEscapes() {
  val record=org.json.JSONObject().put("event",org.json.JSONObject().put("event_id","id").put("symbol","SPY").put("action","enter")).put("timeline",org.json.JSONArray()).put("local",org.json.JSONObject.NULL)
  assertTrue(Diagnostics.describe(record).contains("latency unavailable"))
  val csv=Diagnostics.csv(org.json.JSONArray().put(record))
  assertTrue(csv.startsWith("event_id,symbol,action,diagnostics,evidence_json\r\n\"id\",\"SPY\",\"enter\","))
 }
 @Test fun futureClockAndHugePriceRejected() {
  assertNull(DiagnosticClock.latency(1000,1040,0.0,0.0,1.0,1.0,1001,1040))
  assertNull(Diagnostics.boundedPrice("1e99999999"))
  assertNull(Diagnostics.boundedPrice("1000000000001"))
  assertEquals("1.25",Diagnostics.boundedPrice("1.25"))
 }
 @Test fun csvNeutralizesFormulasAndPreservesRawEvidence() {
  val r=org.json.JSONObject().put("event",org.json.JSONObject().put("event_id","=evil").put("symbol","SPY").put("action","enter")).put("timeline",org.json.JSONArray()).put("relay",org.json.JSONObject().put("observations",org.json.JSONArray()))
  val csv=Diagnostics.csv(org.json.JSONArray().put(r))
  assertTrue(csv.contains("\"'=evil\"")); assertTrue(csv.contains("observations"))
 }
 @Test fun midpointAndWallJump() {
  assertEquals(15.0, DiagnosticClock.probe(1000,1020,20,1025)!!.offset,0.001)
  assertNull(DiagnosticClock.probe(1000,1300,20,1025))
 }
 @Test fun latencyRejectsStaleAndImpossible() {
  assertEquals(20.0, DiagnosticClock.latency(1000,1040,10.0,-10.0,5.0,5.0,1000,1040)!!.first,0.001)
  assertNull(DiagnosticClock.latency(1000,900,0.0,0.0,5.0,5.0,1000,900))
  assertNull(DiagnosticClock.latency(100000,100040,0.0,0.0,5.0,5.0,0,100040))
 }
}

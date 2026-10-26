package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.io.ByteArrayInputStream

class PushDashboardTest {
 @Test fun sharedDashboardFixtures() {
  val raw=javaClass.classLoader!!.getResourceAsStream("copy-dashboard.json")!!.bufferedReader().use { it.readText() }
  val cases=JSONObject(raw).getJSONArray("cases")
  for(i in 0 until cases.length()) {
   val case=cases.getJSONObject(i); val input=case.getJSONObject("input")
   val result=CopyReports.metrics(input.getJSONObject("report"),input.optString("as_of").takeIf { it.isNotBlank() }?.let { java.time.Instant.parse(it) } ?: java.time.Instant.now())
   val expected=case.getJSONObject("expected")
   for(key in listOf("remaining","entry_average","exit_average","gross_realized_pnl","net_realized_pnl","unrealized_estimate"))
    assertEquals(case.getString("id")+":"+key,expected.get(key),result.get(key))
  }
 }
 @Test fun utf8AndMultipleFrames() {
  val frames=mutableListOf<String>()
  EventStreamParser.read(ByteArrayInputStream(": hello\r\nevent: ready\r\ndata: {\"version\":1,\"transport\":\"push\"}\r\n\r\nevent: heartbeat\ndata: {\"server_time_ms\":1}\n\n".toByteArray())) { event,body -> frames.add(event); assertTrue(body.length()>0) }
  assertEquals(listOf("ready","heartbeat"),frames)
 }
 @Test fun unknownFramesIgnoredButStillBounded() {
  var count=0
  EventStreamParser.read(ByteArrayInputStream("event: extension\ndata: not json\n\n".toByteArray())) { _,_->count++ }
  assertEquals(0,count)
  assertThrows(IllegalArgumentException::class.java) { EventStreamParser.read(ByteArrayInputStream(("event: extension\ndata: "+"a".repeat(EventStreamParser.MAX_BYTES)+"\n\n").toByteArray())) { _,_-> } }
 }
 @Test fun malformedKnownAndTruncatedFramesFail() {
  assertThrows(Exception::class.java) { EventStreamParser.read(ByteArrayInputStream("event: events\ndata: nope\n\n".toByteArray())) { _,_-> } }
  assertThrows(Exception::class.java) { EventStreamParser.read(ByteArrayInputStream("event: ready\ndata: {}\n".toByteArray())) { _,_-> } }
  assertThrows(Exception::class.java) { EventStreamParser.read(ByteArrayInputStream(byteArrayOf(0xC3.toByte(),10))) { _,_-> } }
 }
 @Test fun pendingSignalSurvivesBusyConsumerAndCoalesces() {
  val signal=WorkSignal(); signal.wake(); signal.wake(); val start=System.nanoTime(); signal.await(5000)
  assertTrue((System.nanoTime()-start)/1000000<500)
 }
 @Test fun moneyNeverGuessesFeesOrPartialLots() {
  val report=JSONObject("""{"bought":3,"sold":3,"buy_premium":"1.005","sell_premium":"2.010","currency":"USD","multiplier":100} """)
  assertEquals("Gross USD 100.50 · net unavailable (fees unknown)",CopyReports.money(report))
  report.put("fees","0.505"); assertTrue(CopyReports.money(report).contains("net USD 100.00"))
  report.put("sold",2); assertEquals("Gross P&L unavailable",CopyReports.money(report))
  report.put("sold",3).put("multiplier",JSONObject.NULL); assertEquals("Gross P&L unavailable",CopyReports.money(report))
 }
 @Test fun boundedDecimalAndRoundedAverage() {
  assertNull(CopyReports.decimal("1e3")); assertNull(CopyReports.decimal("-1")); assertNull(CopyReports.decimal("1".repeat(81)))
  assertEquals("0.33333333 (rounded)",CopyReports.average(JSONObject("""{"bought":3,"buy_premium":"1"}"""),"buy"))
 }
 @Test fun duplicateCursorUsesExistingDurableProtocol() {
  var accepted=0; var cursor=9L
  val rows=org.json.JSONArray().put(JSONObject().put("cursor",9).put("event",JSONObject()))
  IncomingProtocol.consume(rows,"paper",{cursor},{_,c -> accepted++;cursor=c},{_,_->fail("duplicate must not quarantine")})
  assertEquals(0,accepted); assertEquals(9L,cursor)
 }
}

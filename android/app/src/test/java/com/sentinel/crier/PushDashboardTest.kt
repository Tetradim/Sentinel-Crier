package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import java.io.ByteArrayInputStream

class PushDashboardTest {
 @Test fun metadataFailureRecoversAfterBackoffAndSuccessStaysComplete() {
  var now=0L; var lookups=0; var cached=""; val retry=MetadataRetry { now }
  fun attempt()=retry.resolve("trade",{true},{ lookups++; if(lookups==1) error("temporary"); "verified" },{ cached=it })
  assertFalse(attempt()); assertEquals("",cached)
  now=4999; assertFalse(attempt()); assertEquals(1,lookups)
  now=5000; assertTrue(attempt()); assertEquals("verified",cached)
  now=1000000; assertFalse(attempt()); assertEquals(2,lookups)
 }
 @Test fun metadataRetriesDoubleToFiveMinuteCapAndRemainPerTrade() {
  var now=0L; var lookups=0; val retry=MetadataRetry { now }
  fun attempt(id:String="one")=retry.resolve(id,{true},{ lookups++; error("offline") },{ _:String -> fail("must not cache failure") })
  assertFalse(attempt()); assertEquals(1,lookups)
  assertFalse(attempt("two")); assertEquals(2,lookups)
  for(delay in listOf(5000L,10000L,20000L,40000L,80000L,160000L,300000L,300000L)) {
   now+=delay-1; val prior=lookups; assertFalse(attempt()); assertEquals(prior,lookups)
   now++; assertFalse(attempt()); assertEquals(prior+1,lookups)
  }
 }
 @Test fun metadataScopeLossNeverCachesAndInflightLookupCannotRepeat() {
  var now=0L; var active=false; var lookups=0; var caches=0; val retry=MetadataRetry { now }
  fun attempt()=retry.resolve("trade",{active},{ lookups++; active=false; "verified" },{ caches++ })
  assertFalse(attempt()); assertEquals(0,lookups)
  active=true; assertFalse(attempt()); assertEquals(1,lookups); assertEquals(0,caches)
  now=5000; active=true
  assertTrue(retry.resolve("trade",{active},{
   assertFalse(retry.resolve("trade",{true},{ fail("already in flight"); "duplicate" },{ caches++ }))
   "verified"
  },{ caches++ }))
  assertEquals(1,caches)
 }
 @Test fun staleDashboardFetchCannotOverwriteNewerStreamSnapshot() {
  val config=JSONObject("""{"url":"https://example.test","token":"private","role":"follower","environment":"paper","account":"one"}""")
  fun snapshot(at:String)=JSONObject("""{"version":1,"role":"follower","environment":"paper","generated_at":"$at","events":[],"members":[],"statuses":[],"diagnostics":[]}""")
  CopyDashboardCache.clear()
  CopyDashboardCache.accept(config,snapshot("2026-10-26T12:00:02Z"))
  CopyDashboardCache.accept(config,snapshot("2026-10-26T12:00:01Z"))
  assertEquals("2026-10-26T12:00:02Z",CopyDashboardCache.read(config)!!.getString("generated_at"))
  assertNull(CopyDashboardCache.read(JSONObject(config.toString()).put("account","two")))
  CopyDashboardCache.clear(); assertNull(CopyDashboardCache.read(config))
 }
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

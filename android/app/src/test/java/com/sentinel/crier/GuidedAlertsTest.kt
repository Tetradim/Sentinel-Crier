package com.sentinel.crier

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class GuidedAlertsTest {
 private val baseline=Instant.parse("2026-10-24T12:00:00Z")
 private class Memory:AlertsDocument {
  var json="{}"
  override fun read()=JSONObject(json)
  override fun write(value:JSONObject) { json=value.toString() }
 }
 private class Reads:FillReadPort {
  var identity="account-a"
  var calls=0
  var page=JSONArray()
  var after=""
  var token:String?=null
  var onAccount:()->Unit={}
  override fun account():String { onAccount(); return identity }
  override fun fills(after:String,page:String?):JSONArray { calls++; this.after=after; token=page; return this.page }
 }
 private fun config(env:String="paper",destination:String="https://discord.com/api/webhooks/123/abc")=JSONObject().put("environment",env).put("key","synthetic-key").put("secret","synthetic-secret").put("discordWebhook",destination)
 private fun fill(id:String="fill-1",quantity:String="0.5",price:String="42.07")=JSONObject().put("id",id).put("activity_type","FILL").put("transaction_time","2026-10-24T12:00:01Z").put("symbol","SPY").put("side","buy").put("qty",quantity).put("price",price).put("order_id","broker-order-1")
 private fun ready(g:GuidedAlerts,c:JSONObject=config()) { g.verify(c); g.preview() }
 private fun fail(block:()->Unit) { try { block(); fail("Expected rejection") } catch(_:IllegalArgumentException) {} catch(_:IllegalStateException) {} }
 @Test fun savedConfigAndRestartNeverImplyReadinessOrEnable() {
  val d=Memory(); val r=Reads(); val g=GuidedAlerts(d,{r},now={baseline})
  ready(g); g.enable(); assertTrue(g.isEnabled())
  val reopened=GuidedAlerts(d,{r},now={baseline})
  assertFalse(reopened.isEnabled()); fail { reopened.enable() }; fail { reopened.preview() }; fail { reopened.tick() }; assertEquals(0,r.calls)
 }
 @Test fun previewTestAndPermissionAreSeparateAndTestIsOptional() {
  val d=Memory(); val r=Reads(); var sends=0; val g=GuidedAlerts(d,{r},{_,_-> sends++; JSONObject().put("id","1234") },{baseline})
  fail { g.enable() }; g.verify(config()); fail { g.enable() }; assertTrue(g.preview().contains("TEST MESSAGE")); assertEquals(0,sends)
  g.enable(); assertTrue(g.isEnabled()); assertEquals(0,sends); assertEquals(baseline.toString(),JSONObject(d.json).getJSONObject("scopes").getJSONObject("paper:account-a").getString("after"))
 }
 @Test fun verificationDoesNotRequireTradingPermissionChannelOrRelay() {
  val urls=mutableListOf<String>()
  val reader=AlpacaFillReader(config("live")) { url,headers -> urls.add(url); assertEquals("synthetic-key",headers["APCA-API-KEY-ID"]); JSONObject().put("id","read-account").put("trading_blocked",true).put("status","ACTIVE") }
  assertEquals("read-account",reader.account()); assertEquals(listOf("https://api.alpaca.markets/v2/account"),urls)
 }
 @Test fun readAdapterUsesOnlyAllowlistedAccountAndFillGetUrls() {
  val urls=mutableListOf<String>(); val r=AlpacaFillReader(config()) { url,_ -> urls.add(url); if(url.endsWith("/account")) JSONObject().put("id","a") else JSONArray() }
  r.account(); r.fills(baseline.toString(),"cursor/1")
  assertTrue(urls[1].startsWith("https://paper-api.alpaca.markets/v2/account/activities/FILL?direction=asc&page_size=100&after=")); assertTrue(urls[1].contains("page_token=cursor%2F1")); assertFalse(urls.any { it.contains("/orders") || it.contains("/sync") })
  fail { AlpacaFillReader(config("invalid")) }
 }
 @Test fun brokerActivityFillUsesActualFractionalQuantityAndExecutionPriceOnce() {
  val d=Memory(); val r=Reads(); r.page=JSONArray().put(fill()); val sent=mutableListOf<JSONObject>()
  val g=GuidedAlerts(d,{r},{url,body-> assertTrue(url.endsWith("?wait=true")); sent.add(body); JSONObject().put("id","987") },{baseline})
  ready(g); g.enable(); g.tick(); r.page=JSONArray(); g.tick()
  assertEquals(1,sent.size); assertTrue(sent.single().toString().contains("0.5")); assertTrue(sent.single().toString().contains("42.07")); assertTrue(sent.single().toString().contains("BROKER FILL")); assertEquals("fill-1",r.token); assertEquals(baseline.toString(),r.after)
 }
 @Test fun baselineExcludesHistoricalFillWithoutAdvancingCursor() {
  val d=Memory(); val r=Reads(); var sends=0; val g=GuidedAlerts(d,{r},{_,_-> sends++; JSONObject() },{baseline}); ready(g); g.enable()
  r.page=JSONArray().put(fill().put("transaction_time","2026-10-24T11:59:59Z")); fail { g.tick() }
  assertEquals(0,sends); assertFalse(g.isEnabled()); assertFalse(JSONObject(d.json).getJSONObject("scopes").getJSONObject("paper:account-a").has("page"))
 }
 @Test fun malformedPageHasNoPartialFillPublicationOrCursorAdvance() {
  val d=Memory(); val r=Reads(); val g=GuidedAlerts(d,{r},now={baseline}); ready(g); g.enable(); r.page=JSONArray().put(fill()).put(fill("bad",price="0")); fail { g.tick() }
  val state=JSONObject(d.json).getJSONObject("scopes").getJSONObject("paper:account-a"); assertEquals(0,state.getJSONArray("jobs").length()); assertFalse(state.has("page"))
 }
 @Test fun lostAcknowledgementRemainsUncertainAcrossRestartAndNeverAutomaticallyRetries() {
  val d=Memory(); val r=Reads(); var sends=0; val g=GuidedAlerts(d,{r},{_,_-> sends++; throw java.io.IOException("lost ack") },{baseline}); ready(g); assertTrue(g.test().contains("uncertain")); assertFalse(g.isEnabled())
  val reopened=GuidedAlerts(d,{r},{_,_-> sends++; JSONObject().put("id","1") },{baseline}); ready(reopened); reopened.enable(); reopened.tick(); assertEquals(1,sends); assertTrue(reopened.history().contains("uncertain"))
 }
 @Test fun missingMessageIdDoesNotBecomeSuccessfulTestOrFillEvidence() {
  val g=GuidedAlerts(Memory(),{Reads()},{_,_->JSONObject()},{baseline}); ready(g); assertTrue(g.test().contains("uncertain")); assertFalse(g.isEnabled()); assertFalse(g.history().contains("fill:"))
 }
 @Test fun configurationChangeAndDisconnectInvalidateAllReadiness() {
  val g=GuidedAlerts(Memory(),{Reads()},now={baseline}); ready(g); g.enable(); g.invalidate(); assertFalse(g.isEnabled()); fail { g.test() }; fail { g.enable() }; fail { g.preview() }
  ready(g); g.enable(); g.stop(); assertFalse(g.isEnabled()); fail { g.enable() }
 }
 @Test fun uncertainMessagesBlockDestinationChangeAndRetainHistoryAfterExplicitClose() {
  val d=Memory(); val r=Reads(); val g=GuidedAlerts(d,{r},{_,_->JSONObject()},{baseline}); ready(g); g.test()
  fail { g.verify(config(destination="https://discord.com/api/webhooks/456/xyz")) }; assertEquals("https://discord.com/api/webhooks/123/abc",g.saved().getString("discordWebhook")); assertTrue(g.history().contains("uncertain"))
  g.closeInspected(); ready(g,config(destination="https://discord.com/api/webhooks/456/xyz")); assertTrue(g.history().contains("discarded")); assertTrue(g.history().contains("User closed"))
 }
 @Test fun accountEnvironmentScopesRemainSeparateIncludingInactiveDestinationUncertainty() {
  val d=Memory(); val r=Reads(); val g=GuidedAlerts(d,{r},{_,_->JSONObject()},{baseline}); ready(g); g.test()
  r.identity="account-b"; ready(g); g.enable(); assertFalse(g.history().contains("uncertain")); g.stop()
  r.identity="account-a"; fail { g.verify(config(destination="https://discord.com/api/webhooks/456/xyz")) }
  ready(g,config("live")); assertFalse(g.history().contains("uncertain")); assertEquals(3,JSONObject(d.json).getJSONObject("scopes").length())
 }
 @Test fun changingSetupDuringVerificationDiscardsStaleNetworkCompletion() {
  val d=Memory(); val r=Reads(); val g=GuidedAlerts(d,{r},now={baseline}); r.onAccount={g.invalidate()}; fail { g.verify(config()) }; assertFalse(g.saved().has("account")); fail { g.preview() }
 }
 @Test fun changingSetupDuringFillReadPreventsPublication() {
  val d=Memory(); val r=Reads(); var sends=0; val g=GuidedAlerts(d,{r},{_,_->sends++; JSONObject().put("id","123")},{baseline}); ready(g); g.enable(); r.onAccount={g.invalidate()}; fail { g.tick() }; assertEquals(0,r.calls); assertEquals(0,sends)
 }
 @Test fun reconnectRetainsBaselineAndDeduplicationForSameIdentity() {
  val d=Memory(); val r=Reads(); r.page=JSONArray().put(fill()); var sends=0; val sender:(String,JSONObject)->JSONObject={_,_->sends++; JSONObject().put("id","123")}
  val g=GuidedAlerts(d,{r},sender,{baseline}); ready(g); g.enable(); g.tick(); g.stop()
  val reopened=GuidedAlerts(d,{r},sender,{baseline.plusSeconds(999)}); ready(reopened); reopened.enable(); r.page=JSONArray(); reopened.tick(); assertEquals(baseline.toString(),r.after); assertEquals("fill-1",r.token); assertEquals(1,sends)
 }
 @Test fun stoppedDuringVerificationWriteCannotRestoreSessionEvidence() {
  val memory=Memory(); lateinit var g:GuidedAlerts
  val document=object:AlertsDocument { override fun read()=memory.read(); override fun write(value:JSONObject) { memory.write(value); g.stop() } }
  g=GuidedAlerts(document,{Reads()},now={baseline}); fail { g.verify(config()) }; fail { g.preview() }; fail { g.enable() }; assertFalse(g.isEnabled())
 }
 @Test fun stoppedDuringBaselineWriteCannotReenableAfterPause() {
  val memory=Memory(); lateinit var g:GuidedAlerts; var stopOnWrite=false
  val document=object:AlertsDocument { override fun read()=memory.read(); override fun write(value:JSONObject) { memory.write(value); if(stopOnWrite) g.stop() } }
  g=GuidedAlerts(document,{Reads()},now={baseline}); ready(g); stopOnWrite=true; fail { g.enable() }; assertFalse(g.isEnabled()); fail { g.tick() }
 }
 @Test fun executionWorkerRequiresAnExplicitActionAndRejectsSystemRestoration() {
  assertFalse(SyncService.acceptsStart(null)); assertFalse(SyncService.acceptsStart("")); assertFalse(SyncService.acceptsStart("android.intent.action.MAIN")); assertTrue(SyncService.acceptsStart(SyncService.EXPLICIT_START))
 }

 @Test fun recreationReusesOneDocumentOwnerWhileLateAcknowledgementIsRecorded() {
  val owner=AlertsSessionOwner(); val memory=Memory(); val reads=Reads(); lateinit var original:GuidedAlerts
  original=owner.get { GuidedAlerts(memory,{reads},{_,_->
   original.stop()
   val recreated=owner.get { error("A second writer must not be created") }
   assertSame(original,recreated)
   JSONObject().put("id","555")
  },{baseline}) }
  ready(original); fail { original.test() }; val recreated=owner.get { error("must retain owner") }; assertTrue(recreated.history().contains("delivered")); assertFalse(recreated.isEnabled()); fail { recreated.preview() }
 }
 @Test fun stopDuringTestEnqueuePreventsAnyHttpDispatch() {
  val memory=Memory(); lateinit var g:GuidedAlerts; var stopOnWrite=false; var sends=0
  val document=object:AlertsDocument { override fun read()=memory.read(); override fun write(value:JSONObject) { memory.write(value); if(stopOnWrite) g.stop() } }
  g=GuidedAlerts(document,{Reads()},{_,_-> sends++; JSONObject().put("id","123") },{baseline}); ready(g); stopOnWrite=true; fail { g.test() }; assertEquals(0,sends); assertTrue(g.history().contains("pending"))
 }
 @Test fun stopDuringDispatchClaimPreventsAnyNewHttpSend() {
  val memory=Memory(); lateinit var g:GuidedAlerts; var stopOnClaim=false; var sends=0
  val document=object:AlertsDocument { override fun read()=memory.read(); override fun write(value:JSONObject) { memory.write(value); if(stopOnClaim && value.toString().contains("Dispatch started")) g.stop() } }
  g=GuidedAlerts(document,{Reads()},{_,_-> sends++; JSONObject().put("id","123") },{baseline}); ready(g); stopOnClaim=true; fail { g.test() }; assertEquals(0,sends); assertTrue(g.history().contains("uncertain"))
 }

}

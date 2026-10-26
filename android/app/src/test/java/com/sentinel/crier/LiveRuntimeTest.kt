package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import java.time.Instant
import java.math.BigDecimal

class LiveRuntimeTest {
 private fun config(policy:String="""{"mode":"fixed","fixed_quantity":3}""")=JSONObject().put("account","account").put("role","follower").put("environment","paper").put("url","https://relay.example").put("token","test-pairing").put("execution_policy",JSONObject(policy))
 private fun event(seq:Int=1,action:String="enter",qty:Int=10)=JSONObject().put("version",1).put("event_id","event-$seq").put("trade_id","trade").put("sequence",seq).put("action",action).put("symbol","SPY").put("asset","stock").put("environment","paper").put("quantity",qty).put("limit_price","1.00").put("created_at",Instant.now().minusSeconds(1).toString()).put("expires_at",Instant.now().plusSeconds(20).toString())
 private class Store(val base:EngineTest.Store=EngineTest.Store()):IntentStore by base {
  var snapshot=JSONObject().put("legacy",true); val events=mutableListOf<JSONObject>()
  override fun policy(trade:String)=snapshot
  override fun sourceEvents(trade:String)=events.toList()
  override fun update(client:String,o:JSONObject) {
   base.update(client,o)
   if(o.optInt("filled_qty")>0 && !o.isNull("filled_avg_price") && o.has("filled_avg_price")) base.setMeta("fill:$client",JSONObject().put("filled",o.getInt("filled_qty")).put("average",o.getString("filled_avg_price")).toString())
  }
  override fun updateObserved(client:String,o:JSONObject,timer:String?) { update(client,o); if(timer!=null) base.setMeta("timer:$client",timer) }
  fun receive(c:JSONObject,e:JSONObject) { if(events.isEmpty()) snapshot=LivePolicy.snapshot(c,e); events.add(e); base.rev=Pair(e.getInt("sequence"),e.getString("action") in setOf("exit","cancel")) }
  fun seed(side:String,qty:Int,seq:Int=1,average:String?="1") {
   val client="$side-$seq"; base.os.add(Journal.Order(client,seq,side,"filled","broker-$client",qty))
   if(average!=null) base.setMeta("fill:$client",JSONObject().put("filled",qty).put("average",average).toString())
   if(side=="buy" && !snapshot.getBoolean("legacy")) {
    val e=events.single { it.getInt("sequence")==seq }; val binding=JSONObject()
    for(k in listOf("account","environment","symbol","asset")) binding.put(k,snapshot.getString(k))
    binding.put("currency","USD").put("multiplier",if(e.getString("asset")=="option") 100 else 1)
    val price=e.getString("limit_price")
    base.setMeta("plan:${e.getString("trade_id")}:$seq",JSONObject().put("event",e).put("snapshot",snapshot).put("binding",binding).put("price",price).put("pricing",JSONObject().put("mode","exact_limit").put("bps",100).put("amount","0.02")).put("target",LivePolicy.target(snapshot.getJSONObject("policy"),e.getInt("quantity"),price,binding.getInt("multiplier"),0,BigDecimal.ZERO)).put("baseline_bought",0).put("baseline_spent","0").toString())
   }
  }
 }
 private class Checked(val fake:EngineTest.Fake=EngineTest.Fake()):BrokerPort by fake {
  var currency="USD"; var preflight:(()->Unit)?=null; var checked=0
  override fun binding(event:JSONObject)=JSONObject().put("account","account").put("environment","paper").put("symbol",event.getString("symbol")).put("asset",event.getString("asset")).put("currency",currency).put("multiplier",if(event.getString("asset")=="option") 100 else 1)
  override fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject {
   checked++; preflight?.invoke(); if(!LivePolicy.equivalent(binding(event),plan.getJSONObject("binding"))) throw Superseded()
   return fake.submit(event,client,quantity,sell,canSubmit)
  }
 }
 @Test fun receiptPinsPolicyWhileLegacyAndHostTradesStayUnscaled() {
  val c=config(); val e=event(); val s=Store(); val b=Checked(); s.receive(c,e)
  c.put("execution_policy",JSONObject("""{"mode":"fixed","fixed_quantity":9}"""))
  Engine(s,c,b) { false }.step(e); assertEquals(3,b.fake.quantity); assertEquals(1,b.checked)
  val host=config().put("role","host"); val hs=Store(); hs.receive(host,e); val hb=Checked(); Engine(hs,host,hb) { false }.step(e); assertEquals(10,hb.fake.quantity); assertEquals(0,hb.checked)
  val legacy=Store(); val lb=Checked(); Engine(legacy,c,lb) { false }.step(e); assertEquals(10,lb.fake.quantity); assertEquals(0,lb.checked)
 }
 @Test fun freezeBeforeUnknownSubmissionSurvivesRestartAndSettingsChanges() {
  val c=config(); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); b.fake.submissionError=HttpError(500)
  assertThrows(HttpError::class.java) { Engine(s,c,b) { false }.step(e) }
  assertEquals(3,JSONObject(s.meta("plan:trade:1")).getInt("target")); assertEquals("unknown",s.base.os.single().state)
  c.put("mode","bounded_limit").put("amount","0.50").put("bps",1000)
  Engine(s,c,b) { false }.step(e); assertEquals(1,b.checked); assertFalse(s.base.done)
 }
 @Test fun finalPauseRevisionAccountAndMetadataChangesRefuseKnownSubmission() {
  for(change in listOf("pause","revision","account","metadata","cap")) {
   val c=config(); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); var pause=false
   b.preflight={ when(change) { "pause"->pause=true; "revision"->s.base.rev=Pair(2,false); "account"->c.put("account","different"); "metadata"->b.currency="EUR"; "cap"->c.put("maxQuantity",1) } }
   Engine(s,c,b) { pause }.step(e); assertEquals(change,0,b.fake.posts); assertEquals(change,"superseded",s.base.os.single().state)
  }
 }
 @Test fun sourceScopeAndUnsupportedCheckedAdapterNeverDispatch() {
  val c=config().put("token",""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked()
  assertThrows(IllegalArgumentException::class.java) { Engine(s,c,b) { false }.step(e) }; assertEquals(0,b.fake.posts)
  val good=config(); val store=Store(); store.receive(good,e)
  val unsupported=object:BrokerPort by b { override fun binding(event:JSONObject):JSONObject=throw IllegalArgumentException("unsupported") }
  assertThrows(IllegalArgumentException::class.java) { Engine(store,good,unsupported) { false }.step(e) }; assertTrue(store.base.os.isEmpty())
 }
 @Test fun replaceBudgetUsesAllPurchaseCostsAndSalesNeverReplenishIt() {
  val c=config("""{"mode":"budget","budget":"10"}"""); val s=Store(); val first=event(); s.receive(c,first); s.seed("buy",4,average="1"); s.seed("sell",2,seq=2)
  val replacement=event(3,"replace").put("limit_price","2"); s.receive(c,replacement); val b=Checked()
  Engine(s,c,b) { false }.step(replacement); assertEquals(3,b.fake.quantity); assertEquals(7,JSONObject(s.meta("plan:trade:3")).getInt("target"))
  val missing=Store(); missing.receive(c,first); missing.seed("buy",4,average=null); missing.receive(c,replacement)
  assertThrows(IllegalArgumentException::class.java) { Engine(missing,c,Checked()) { false }.step(replacement) }; assertFalse(missing.meta("plan:trade:3").isNotBlank())
 }
 @Test fun fixedReplaceSubtractsPurchasesRatherThanNetHoldings() {
  val c=config("""{"mode":"fixed","fixed_quantity":5}"""); val s=Store(); s.receive(c,event()); s.seed("buy",4); s.seed("sell",2,2); val e=event(3,"replace"); s.receive(c,e); val b=Checked()
  Engine(s,c,b) { false }.step(e); assertEquals(1,b.fake.quantity)
 }
 @Test fun proportionalUsesCompleteCumulativeIntentAndFullCloseBoundsTrackedUnits() {
  val c=config("""{"exit_mode":"proportional"}"""); val s=Store(); s.receive(c,event()); s.seed("buy",7); s.receive(c,event(2,"exit",2)); s.seed("sell",1,2); val e=event(3,"exit",3); s.receive(c,e); val b=Checked(); b.fake.available=100
  Engine(s,c,b) { true }.step(e); assertEquals(2,b.fake.quantity)
  val gap=Store(); gap.receive(c,event()); gap.seed("buy",7); gap.receive(c,e)
  assertThrows(IllegalArgumentException::class.java) { Engine(gap,c,Checked()) { true }.step(e) }
  val full=config("""{"exit_mode":"close_tracked"}"""); val fs=Store(); fs.receive(full,event()); fs.seed("buy",3,average=null); fs.seed("sell",1,2); val exit=event(3,"exit",1); fs.receive(full,exit); val fb=Checked(); fb.fake.available=100
  Engine(fs,full,fb) { true }.step(exit); assertEquals(2,fb.fake.quantity)
 }
 @Test fun acknowledgedMonotonicTimerCancelsPartialBuyAndCannotBeReopened() {
  val c=config("""{"mode":"fixed","fixed_quantity":3,"entry_timeout_seconds":2}"""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); var mono=1000L
  val engine=Engine(s,c,b,monotonic={mono}) { false }; engine.step(e)
  assertEquals("",s.meta("timer:si-event-1-b"))
  b.fake.remote!!.put("status","partially_filled").put("filled_qty","1").put("filled_avg_price","1")
  engine.step(e); assertEquals(0,b.fake.canceled); mono+=2000; engine.step(e)
  assertEquals(1,b.fake.canceled); assertEquals("true",s.meta("entry_closed:trade")); assertEquals(1,s.base.os.single().filled)
  b.fake.remote!!.put("status","canceled"); val replacement=event(2,"replace"); s.receive(c,replacement); engine.step(replacement); assertEquals(1,b.fake.posts)
 }
 @Test fun restartCancelsOnlyPreviouslyAcknowledgedWorkingBuyAfterFreshLookup() {
  val c=config("""{"mode":"fixed","fixed_quantity":3,"entry_timeout_seconds":60}"""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked()
  val first=Engine(s,c,b,monotonic={1000}) { false }; first.step(e); first.step(e)
  val remote=b.fake.remote; b.fake.remote=null
  Engine(s,c,b,monotonic={1000}) { false }.step(e); assertEquals(0,b.fake.canceled)
  b.fake.remote=remote
  Engine(s,c,b,monotonic={1000}) { false }.step(e); assertEquals(1,b.fake.canceled)
  val unknown=Store(); unknown.receive(c,e); val ub=Checked(); val initial=Engine(unknown,c,ub,monotonic={1000}) { false }; initial.step(e)
  unknown.base.os[0]=unknown.base.os[0].copy(broker="",state="unknown")
  val restarted=Engine(unknown,c,ub,monotonic={90000}) { false }; restarted.step(e); assertEquals(0,ub.fake.canceled); assertNotEquals("",unknown.meta("timer:si-event-1-b"))
 }
 @Test fun missingAcknowledgementEvidenceCannotRestartAnAcknowledgedTimer() {
  val c=config("""{"entry_timeout_seconds":60}"""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked()
  val first=Engine(s,c,b,monotonic={1000}) { false }; first.step(e); first.step(e); s.setMeta("timer:si-event-1-b","")
  Engine(s,c,b,monotonic={2000}) { false }.step(e); assertEquals(1,b.fake.canceled); assertEquals("true",s.meta("entry_closed:trade"))
 }
 @Test fun mutatedFrozenTargetIsRejectedBeforeAnyReservation() {
  val c=config(); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); val first=Engine(s,c,b) { false }; first.step(e)
  val original=JSONObject(s.meta("plan:trade:1")); val plan=JSONObject(original.toString()); s.base.os.clear(); s.setMeta("plan:trade:1",plan.put("target",999).toString())
  assertThrows(IllegalArgumentException::class.java) { Engine(s,c,b) { false }.step(e) }; assertEquals(1,b.fake.posts); assertTrue(s.base.os.isEmpty())
  s.setMeta("plan:trade:1",JSONObject(original.toString()).put("price","100").toString())
  assertThrows(IllegalArgumentException::class.java) { Engine(s,c,b) { false }.step(e) }; assertEquals(1,b.fake.posts)
 }
 @Test fun historyGapAllowsFreshWorkingBuyCancellationBeforeBlockingSale() {
  val c=config("""{"exit_mode":"proportional"}"""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); val engine=Engine(s,c,b) { false }; engine.step(e)
  val exit=event(3,"exit",3); s.receive(c,exit); engine.step(exit); assertEquals(1,b.fake.canceled)
  b.fake.remote!!.put("status","canceled").put("filled_qty","2").put("filled_avg_price","1")
  assertThrows(IllegalArgumentException::class.java) { engine.step(exit) }; assertEquals(1,b.fake.posts)
 }
 @Test fun missingAndContradictoryPolicyRecordsAreNotLegacyDefaults() {
  assertThrows(Exception::class.java) { LivePolicy.validateSnapshot(JSONObject()) }
  assertThrows(IllegalArgumentException::class.java) { LivePolicy.validateSnapshot(JSONObject().put("legacy",true).put("policy",JSONObject())) }
  val c=config(); val snapshot=LivePolicy.snapshot(c,event()); assertFalse(LivePolicy.validateSnapshot(snapshot).getBoolean("legacy"))
 }
 @Test fun staleOrNegativeFillEvidenceBlocksBudgetReplacement() {
  val c=config("""{"mode":"budget","budget":"10"}""")
  for(evidence in listOf("""{"filled":4,"average":"-1"}""","""{"filled":4,"average":"0"}""","""{"filled":3,"average":"1"}""","""{"filled":4.0,"average":"1"}""")) {
   val s=Store(); s.receive(c,event()); s.seed("buy",4); s.setMeta("fill:buy-1",evidence); val replacement=event(2,"replace"); s.receive(c,replacement); val b=Checked()
   assertThrows(IllegalArgumentException::class.java) { Engine(s,c,b) { false }.step(replacement) }; assertEquals(0,b.fake.posts)
  }
 }
 @Test fun uncertainTimerCancellationRetainsClosedEntryAndRacingFillOwnership() {
  val c=config("""{"entry_timeout_seconds":1}"""); val e=event(); val s=Store(); s.receive(c,e); val b=Checked(); var mono=1000L
  val engine=Engine(s,c,b,monotonic={mono}) { false }; engine.step(e); engine.step(e); mono+=1000; b.fake.cancelError=HttpError(500)
  assertThrows(HttpError::class.java) { engine.step(e) }; assertEquals("true",s.meta("entry_closed:trade")); assertEquals("cancel_unknown",s.base.os.single().state)
  b.fake.remote!!.put("status","canceled").put("filled_qty","2").put("filled_avg_price","1"); b.fake.cancelError=null
  val replacement=event(2,"replace"); s.receive(c,replacement); engine.step(replacement); assertEquals(1,b.fake.posts); assertEquals(2,s.base.os.single().filled)
 }
 @Test fun missingPriorBuyPlanBlocksReplacementButNotQuantityProvenExit() {
  val c=config("""{"exit_mode":"close_tracked"}"""); val s=Store(); s.receive(c,event()); s.seed("buy",4); s.setMeta("plan:trade:1","")
  val replacement=event(2,"replace"); s.receive(c,replacement); val b=Checked()
  assertThrows(IllegalArgumentException::class.java) { Engine(s,c,b) { false }.step(replacement) }; assertEquals(0,b.fake.posts)
  val exit=event(3,"exit",1); s.receive(c,exit); Engine(s,c,b) { true }.step(exit); assertEquals(4,b.fake.quantity)
 }
 @Test fun sharedEntryFixturesMatchTargetArithmetic() {
  val resource=javaClass.classLoader!!.getResourceAsStream("policy-preview.json") ?: error("fixture missing")
  val fixtures=JSONObject(resource.bufferedReader().use { it.readText() }).getJSONArray("entry")
  for(i in 0 until fixtures.length()) {
   val row=fixtures.getJSONObject(i); val input=row.getJSONObject("input"); val expected=row.getJSONObject("expected"); val asset=input.getString("asset")
   val multiplier=try { LivePolicy.multiplier(asset,if(input.has("contract_size")) input.getInt("contract_size") else null) } catch(_:IllegalArgumentException) { assertEquals(row.getString("id"),"blocked",expected.getString("decision")); continue }
   val p=input.optJSONObject("policy") ?: JSONObject(); val price=if(input.has("limit_price")) input.getString("limit_price") else null
   if(expected.getString("decision")=="eligible" || expected.optString("reason")=="below_one_unit") assertEquals(row.getString("id"),expected.getInt("target_quantity"),LivePolicy.target(p,input.getInt("source_quantity"),price,multiplier,0,BigDecimal.ZERO))
   else assertThrows(row.getString("id"),IllegalArgumentException::class.java) { LivePolicy.target(p,input.getInt("source_quantity"),price,multiplier,0,BigDecimal.ZERO) }
  }
 }
}

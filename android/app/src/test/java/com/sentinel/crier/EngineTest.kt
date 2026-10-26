package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import java.time.Instant
class EngineTest {
 class Store:IntentStore {
  val reasons=mutableListOf<String>()
  override fun diagnostic(id:String,stage:String,detail:String) { reasons.add("$stage:$detail") }
  var rev=Pair(1,false); val os=mutableListOf<Journal.Order>(); var done=false
  val metadata=mutableMapOf("device" to "device")
  override fun meta(key:String)=metadata[key] ?: ""
  override fun setMeta(key:String,value:String) { metadata[key]=value }
  override fun revision(trade:String)=rev
  override fun orders(trade:String)=os.toList()
  override fun mark(id:String,outbox:Boolean) { done=true }
  override fun state(client:String,state:String) { val o=os.first { it.client==client }; os[os.indexOf(o)]=o.copy(state=state) }
  override fun update(client:String,o:JSONObject) { val old=os.first { it.client==client }; os[os.indexOf(old)]=old.copy(state=o.getString("status"),broker=o.getString("id"),filled=o.getInt("filled_qty")) }
  override fun unknown(client:String,trade:String,seq:Int,side:String) { os.add(Journal.Order(client,seq,side,"unknown","",0)) }
  override fun create(action:String,symbol:String,asset:String,quantity:Int,price:String,environment:String,tradeId:String)=JSONObject()
 }
 class Fake:BrokerPort {
  var submissionError:HttpError?=null
  var beforeSubmit:(()->Unit)?=null
  var cancelError:Exception?=null
  val responses=mutableMapOf<String,JSONObject>(); val unavailable=mutableSetOf<String>(); val lookups=mutableListOf<String>(); val canceledIds=mutableListOf<String>()
  var posts=0; var canceled=0; var quantity=0; var remote:JSONObject?=null; var available=5
  override fun account()="account"
  override fun order(client:String):JSONObject? { lookups.add(client); return if(client in unavailable) null else if(remote?.optString("client_order_id")==client) remote else responses[client] }
  override fun cancel(id:String) { canceled++; canceledIds.add(id); cancelError?.let { throw it } }
  override fun holdings(symbol:String)=available
  override fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean):JSONObject { beforeSubmit?.invoke(); if(!canSubmit()) throw Superseded(); submissionError?.let { throw it }; remote?.let { responses[it.getString("client_order_id")]=it }; posts++; this.quantity=quantity; val r=JSONObject().put("status","accepted").put("id","broker").put("filled_qty","0").put("client_order_id",client).put("symbol",event.getString("symbol")).put("side",if(sell) "sell" else "buy").put("qty",quantity.toString()); remote=r; return r }
 }
 private fun event(action:String="enter",seq:Int=1)=JSONObject().put("event_id","event").put("trade_id","trade").put("sequence",seq).put("action",action).put("symbol","SPY").put("asset","stock").put("quantity",5).put("limit_price","1.00").put("created_at",Instant.now().toString()).put("expires_at",Instant.now().plusSeconds(30).toString())
 @Test fun pricingChangedDuringPreflightNeverPostsTheOldOrder() {
  val s=Store(); val b=Fake(); val config=JSONObject().put("account","account").put("role","follower")
  b.beforeSubmit={ config.put("mode","bounded_limit") }
  Engine(s,config,b) { false }.step(event())
  assertEquals(0,b.posts); assertEquals("superseded",s.os.single().state)
  assertTrue(s.reasons.any { it.contains("pricing_changed") })
 }
 @Test fun changedClockDefersEntryAndDoesNotBlockCancellation() {
  var wall=Instant.now(); val base=wall; var mono=1000L; val s=Store(); val b=Fake()
  val e=event().put("created_at",base.minusSeconds(1).toString()).put("expires_at",base.plusSeconds(20).toString())
  val engine=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={wall},entryClock=EntryClock({wall},{mono})) { false }
  wall=wall.plusSeconds(60); engine.step(e); assertEquals(0,b.posts); assertFalse(s.done)
  assertTrue(s.reasons.any { it.contains("clock_changed") })
  wall=base; engine.step(e); assertEquals(1,b.posts)
  val (cancelStore,cancelBroker)=cancelSetup(); val cancelClock=EntryClock({wall},{mono}); wall=wall.plusSeconds(60)
  Engine(cancelStore,JSONObject().put("account","account").put("role","follower"),cancelBroker,clock={wall},entryClock=cancelClock) { false }.step(event("cancel",2))
  assertEquals(1,cancelBroker.canceled)
 }
 @Test fun clockChangedInsidePreflightIsRetainedAsKnownNotSubmitted() {
  var wall=Instant.now(); val base=wall; val s=Store(); val b=Fake()
  val e=event().put("created_at",base.minusSeconds(1).toString()).put("expires_at",base.plusSeconds(20).toString())
  b.beforeSubmit={wall=wall.minusSeconds(60)}
  Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={wall},entryClock=EntryClock({wall},{1000L})) { false }.step(e)
  assertEquals(0,b.posts); assertEquals("superseded",s.os.single().state)
  assertTrue(s.reasons.any { it.contains("clock_changed") })
 }
 @Test fun backwardSlewCannotOpenAFutureEntryCreationGate() {
  val base=Instant.now(); var wall=base; var mono=1000L; val s=Store(); val b=Fake()
  val engine=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={wall},entryClock=EntryClock({wall},{mono})) { false }
  val e=event().put("created_at",base.plusMillis(500).toString()).put("expires_at",base.plusSeconds(20).toString())
  wall=wall.minusSeconds(1); mono+=1000; engine.step(e)
  assertEquals(0,b.posts); assertFalse(s.done); assertTrue(s.reasons.any { it.contains("future_created_at") })
 }
 @Test fun tightenedQuantityCapDuringPreflightPreventsPost() {
  val s=Store(); val b=Fake(); val config=JSONObject().put("account","account").put("role","follower")
  b.beforeSubmit={config.put("maxQuantity",2)}
  Engine(s,config,b) { false }.step(event())
  assertEquals(0,b.posts); assertEquals("superseded",s.os.single().state)
  assertTrue(s.reasons.any { it.contains("max_quantity") })
 }
 private fun engine(s:Store,b:Fake)=Engine(s,JSONObject().put("account","account").put("role","follower"),b) { false }
 @Test fun clientIdMatchesAcrossInstallations() { val first=Store(); val second=Store(); engine(first,Fake()).step(event()); engine(second,Fake()).step(event()); assertEquals("si-event-b",first.os.single().client); assertEquals(first.os.single().client,second.os.single().client) }
  @Test fun tombstonePreventsLateEntry() { val s=Store(); s.rev=Pair(2,true); val b=Fake(); engine(s,b).step(event()); assertEquals(0,b.posts) }
 @Test fun duplicateClient422StaysUnknown() { val s=Store(); val b=Fake(); b.submissionError=HttpError(422); try { engine(s,b).step(event()); fail("Expected duplicate response") } catch(_:HttpError) {} ; assertEquals("unknown",s.os.single().state); b.submissionError=null; engine(s,b).step(event()); assertEquals(0,b.posts) }
  @Test fun unknown404NeverResubmits() { val s=Store(); s.os.add(Journal.Order("client",1,"buy","unknown","",0)); val b=Fake(); engine(s,b).step(event()); assertEquals(0,b.posts); assertFalse(s.done) }
 @Test fun exitWaitsForTerminalThenCapsOwnedShares() {
  val s=Store(); s.rev=Pair(2,true); s.setMeta("quantity:client","5"); s.os.add(Journal.Order("client",1,"buy","accepted","broker",2)); val b=Fake()
  b.remote=JSONObject().put("status","partially_filled").put("id","broker").put("filled_qty","2").put("client_order_id","client").put("symbol","SPY").put("side","buy").put("qty","5")
  val e=engine(s,b); e.step(event("exit",2)); assertEquals(1,b.canceled); assertEquals(0,b.posts)
  b.remote=JSONObject().put("status","canceled").put("id","broker").put("filled_qty","3").put("client_order_id","client").put("symbol","SPY").put("side","buy").put("qty","5"); b.available=2
  e.step(event("exit",2)); assertEquals(1,b.posts); assertEquals(2,b.quantity)
 }
 @Test fun replacementOnlyBuysOutstandingTarget() { val s=Store(); s.rev=Pair(2,false); s.os.add(Journal.Order("old",1,"buy","canceled","broker",3)); s.setMeta("quantity:old","5"); val b=Fake(); b.remote=JSONObject().put("id","broker").put("client_order_id","old").put("symbol","SPY").put("side","buy").put("qty","5").put("filled_qty","3").put("status","canceled"); engine(s,b).step(event("replace",2)); assertEquals(2,b.quantity) }
 @Test fun preflightInvalidationPreventsPost() { val s=Store(); val b=Fake(); b.beforeSubmit={ s.rev=Pair(2,true) }; engine(s,b).step(event()); assertEquals(0,b.posts); assertEquals("superseded",s.os.single().state) }
 @Test fun partialExitContinuesOnlyAfterFill() { val s=Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("buy",1,"buy","filled","buyid",5)); s.setMeta("quantity:buy","5"); val b=Fake(); b.remote=JSONObject().put("id","buyid").put("client_order_id","buy").put("symbol","SPY").put("side","buy").put("qty","5").put("filled_qty","5").put("status","filled"); b.available=2; val e=engine(s,b); e.step(event("exit",2)); assertEquals(2,b.quantity); assertEquals("si-event-s0",s.os.last().client); b.remote!!.put("status","filled").put("filled_qty","2"); b.available=0; e.step(event("exit",2)); assertEquals(1,b.posts); assertFalse(s.done); b.available=3; e.step(event("exit",2)); assertEquals(2,b.posts); assertEquals(3,b.quantity); assertNotEquals(s.os[1].client,s.os[2].client) }
  @Test fun replacementDoesNotCancelItsOwnNewOrder() { val s=Store(); s.rev=Pair(2,false); val b=Fake(); val e=engine(s,b); e.step(event("replace",2)); e.step(event("replace",2)); assertEquals(1,b.posts); assertEquals(0,b.canceled) }

 private fun cancelSetup():Pair<Store,Fake> {
  val s=Store(); s.rev=Pair(2,true); s.setMeta("quantity:client","5"); s.os.add(Journal.Order("client",1,"buy","accepted","broker",0))
  val b=Fake(); b.remote=JSONObject().put("status","accepted").put("id","broker").put("filled_qty","0").put("client_order_id","client").put("symbol","SPY").put("side","buy").put("qty","5")
  return s to b
 }
 @Test fun cancelFailureRetriesAfterReconciliationAndRestartCooldown() {
  val (s,b)=cancelSetup(); var now=Instant.parse("2026-01-01T00:00:00Z")
  fun fresh()=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }
  b.cancelError=HttpError(503); try { fresh().step(event("cancel",2)); fail() } catch(_:HttpError) {}
  assertEquals(1,b.canceled); b.cancelError=null; now=now.plusMillis(4999); fresh().step(event("cancel",2)); assertEquals(1,b.canceled)
  now=now.plusMillis(1); fresh().step(event("cancel",2)); assertEquals(2,b.canceled); assertEquals(0,b.posts)
 }
 @Test fun pendingCancelAndTerminalFillSuppressDeleteAndExitCapsHoldings() {
  val (s,b)=cancelSetup(); b.remote!!.put("status","pending_cancel")
  engine(s,b).step(event("exit",2)); assertEquals(0,b.canceled); assertEquals(0,b.posts)
  b.remote!!.put("status","filled").put("filled_qty","5"); b.available=3
  engine(s,b).step(event("exit",2)); assertEquals(0,b.canceled); assertEquals(3,b.quantity)
 }
 @Test fun legacyCancelMarkerRetriesAndBrokerIdentityRemainsPinned() {
  val (s,b)=cancelSetup(); s.setMeta("cancel:client","requested"); engine(s,b).step(event("cancel",2)); assertEquals(1,b.canceled)
  b.remote!!.put("id","different"); try { engine(s,b).step(event("cancel",2)); fail() } catch(_:IllegalArgumentException) {}
  assertEquals("broker",s.os.single().broker); assertEquals(1,b.canceled)
 }
 @Test fun futureFractionalEntryRemainsPendingThenExecutes() {
  val s=Store(); val b=Fake(); var now=Instant.parse("2026-01-01T00:00:00.100Z")
  val e=event().put("created_at","2026-01-01T00:00:00.200Z").put("expires_at","2026-01-01T00:00:10.200Z")
  val engine=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }
  engine.step(e); assertFalse(s.done); assertEquals(0,b.posts)
  now=now.plusMillis(100); engine.step(e); assertEquals(1,b.posts)
 }

 @Test fun crashBeforeDeleteUsesPersistedCooldownAndFreshSnapshot() {
  val (s,b)=cancelSetup(); var now=Instant.parse("2026-01-01T00:00:00Z")
  s.setMeta("cancel:client","requested"); s.setMeta("cancel_attempt_ms:client",now.toEpochMilli().toString()); s.state("client","cancel_unknown")
  fun restarted()=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }
  restarted().step(event("cancel",2)); assertEquals(0,b.canceled)
  now=now.plusSeconds(5); restarted().step(event("cancel",2)); assertEquals(1,b.canceled)
 }
 @Test fun futureWholeSecondDoesNotCompleteAndFractionalAgeLimitIsExact() {
  val s=Store(); val b=Fake(); var now=Instant.parse("2026-01-01T00:00:00.100Z")
  val e=event().put("created_at","2026-01-01T00:00:01.200Z").put("expires_at","2026-01-01T00:00:30Z")
  val engine=Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }
  engine.step(e); assertFalse(s.done); assertEquals(0,b.posts)
  now=Instant.parse("2026-01-01T00:00:11.201Z"); engine.step(e); assertTrue(s.done); assertEquals(0,b.posts)
 }

 @Test fun exactExpiryNeverSubmits() {
  val s=Store(); val b=Fake(); val now=Instant.parse("2026-01-01T00:00:05Z")
  val e=event().put("created_at","2026-01-01T00:00:00Z").put("expires_at",now.toString())
  Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }.step(e)
  assertEquals(0,b.posts); assertTrue(s.done)
 }
 @Test fun expiryReachedDuringPreflightNeverSubmits() {
  val s=Store(); val b=Fake(); var now=Instant.parse("2026-01-01T00:00:04.999Z")
  val e=event().put("created_at","2026-01-01T00:00:00Z").put("expires_at","2026-01-01T00:00:05Z")
  b.beforeSubmit={ now=now.plusMillis(1) }
  Engine(s,JSONObject().put("account","account").put("role","follower"),b,clock={now},entryClock=EntryClock({now},{now.toEpochMilli()})) { false }.step(e)
  assertEquals(0,b.posts); assertEquals("superseded",s.os.single().state)
 }
 @Test fun definitiveSubmissionAndAuthenticationRejectionsDoNotRepostAfterRestart() {
  for(code in listOf(400,401,403)) {
   val s=Store(); val b=Fake(); b.submissionError=HttpError(code)
   try { engine(s,b).step(event()); fail() } catch(_:HttpError) {}
   assertEquals("rejected",s.os.single().state); b.submissionError=null
   engine(s,b).step(event()); assertEquals(0,b.posts); assertTrue(s.done)
  }
 }
 @Test fun optionDecimalPremiumPartialFillAndUnrelatedHoldingsStayBoundedAfterResume() {
  val (s,b)=cancelSetup(); var current=event("exit",2).put("symbol","SPY261218C00750000").put("asset","option").put("limit_price","0.20")
  b.remote!!.put("symbol",current.getString("symbol")).put("status","partially_filled").put("filled_qty","2").put("filled_avg_price","0.23"); b.available=100
  assertTrue(engine(s,b).reconcile(current)); assertEquals(0,b.posts)
  engine(s,b).step(current); assertEquals(1,b.canceled); assertEquals(0,b.posts)
  b.remote!!.put("status","canceled"); engine(s,b).step(current)
  assertEquals(2,b.quantity); assertEquals(1,b.posts)
 }
 @Test fun resumeUnknownOrderAndDecliningFillEvidenceCannotAuthorizeSubmission() {
  val (s,b)=cancelSetup(); b.remote=null
  assertFalse(engine(s,b).reconcile(event("exit",2))); assertEquals(0,b.posts)
  s.os[0]=s.os[0].copy(filled=2)
  b.remote=JSONObject().put("id","broker").put("client_order_id","client").put("symbol","SPY").put("side","buy").put("qty","5").put("filled_qty","1").put("status","canceled")
  assertFalse(engine(s,b).reconcile(event("exit",2)))
  assertEquals(2,s.os[0].filled); assertEquals(0,b.posts)
 }
}

package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import java.time.Instant
class TerminalReconciliationTest {
 private fun config()=JSONObject().put("account","account").put("role","follower")
 private fun event(action:String="exit",seq:Int=2)=JSONObject().put("event_id","event-$seq").put("trade_id","trade").put("sequence",seq).put("action",action).put("symbol","SPY").put("asset","stock").put("quantity",5).put("limit_price","1").put("created_at",Instant.now().minusSeconds(1).toString()).put("expires_at",Instant.now().plusSeconds(20).toString())
 private fun order(client:String="buy",side:String="buy",filled:Int=3,qty:Int=5,id:String="broker-$client",state:String="canceled")=JSONObject().put("id",id).put("client_order_id",client).put("symbol","SPY").put("side",side).put("qty",qty.toString()).put("filled_qty",filled.toString()).put("filled_avg_price","1").put("status",state)
 @Test fun terminalBuyUnavailableBlocksExitThenRecoverySubmitsOnce() {
  val s=EngineTest.Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("buy",1,"buy","canceled","broker-buy",3)); s.setMeta("quantity:buy","5"); val b=EngineTest.Fake(); val engine=Engine(s,config(),b) { true }
  engine.step(event()); assertEquals(0,b.posts); assertFalse(s.done); assertFalse(engine.reconciliationHealthy)
  b.remote=order(filled=4); engine.step(event()); assertEquals(1,b.posts); assertEquals(4,b.quantity)
  engine.step(event()); assertEquals(1,b.posts)
 }
 @Test fun terminalBuyUnavailableBlocksReplace() {
  val s=EngineTest.Store(); s.rev=Pair(2,false); s.os.add(Journal.Order("buy",1,"buy","filled","broker-buy",3)); s.setMeta("quantity:buy","5"); val b=EngineTest.Fake()
  Engine(s,config(),b) { false }.step(event("replace")); assertEquals(0,b.posts); assertFalse(s.done)
 }
 @Test fun everyBrokerBackedTerminalStatusNeedsFreshEvidence() {
  for(status in listOf("filled","canceled","expired","replaced","rejected")) {
   val s=EngineTest.Store(); s.rev=Pair(2,false); s.os.add(Journal.Order("buy",1,"buy",status,"broker-buy",0)); s.setMeta("quantity:buy","5"); val b=EngineTest.Fake()
   Engine(s,config(),b) { false }.step(event("replace")); assertEquals(status,0,b.posts); assertEquals(listOf("buy"),b.lookups); assertFalse(s.done)
  }
 }
 @Test fun terminalSellUnavailableAndLaterFillRefreshPreventOverselling() {
  val s=EngineTest.Store(); s.rev=Pair(3,true); s.os.add(Journal.Order("buy",1,"buy","filled","broker-buy",5)); s.os.add(Journal.Order("sell",2,"sell","canceled","broker-sell",2)); s.setMeta("quantity:buy","5"); s.setMeta("quantity:sell","3"); val b=EngineTest.Fake(); b.available=100
  b.responses["buy"]=order(filled=5,state="filled"); val engine=Engine(s,config(),b) { true }
  engine.step(event(seq=3)); assertEquals(0,b.posts); assertFalse(s.done)
  b.responses["sell"]=order("sell","sell",3,3,state="filled")
  engine.step(event(seq=3)); assertEquals(1,b.posts); assertEquals(2,b.quantity); assertEquals(3,s.os.first { it.client=="sell" }.filled)
  engine.step(event(seq=3)); assertEquals(1,b.posts)
 }
 @Test fun malformedTerminalBindingsAndRegressingEvidenceNeverAuthorizeExit() {
  for(change in listOf("id","symbol","side","qty","client_order_id","filled_qty","average_zero","average_negative","status")) {
   val s=EngineTest.Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("buy",1,"buy","canceled","broker-buy",3)); s.setMeta("quantity:buy","5"); val b=EngineTest.Fake(); val r=order()
   when(change) { "id"->r.put("id","changed"); "symbol"->r.put("symbol","QQQ"); "side"->r.put("side","sell"); "qty"->r.put("qty","6"); "client_order_id"->r.put("client_order_id","different"); "filled_qty"->r.put("filled_qty","2"); "average_zero"->r.put("filled_avg_price","0"); "average_negative"->r.put("filled_avg_price","-1"); "status"->r.put("status","invented") }
   b.responses["buy"]=r
   assertThrows(change,IllegalArgumentException::class.java) { Engine(s,config(),b) { true }.step(event()) }; assertEquals(change,0,b.posts); assertEquals(3,s.os.single().filled)
  }
 }
 @Test fun terminalAccountChangeRefusesBeforeLookup() {
  val s=EngineTest.Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("buy",1,"buy","filled","broker-buy",3)); val b=EngineTest.Fake(); val changed=object:BrokerPort by b { override fun account()="other-account" }
  assertThrows(IllegalArgumentException::class.java) { Engine(s,config(),changed) { true }.step(event()) }; assertEquals(0,b.posts); assertTrue(b.lookups.isEmpty())
 }
 @Test fun onlyExplicitZeroFillLocalRefusalsSkipLookup() {
  for(state in listOf("superseded","rejected")) {
   val s=EngineTest.Store(); s.rev=Pair(2,false); s.os.add(Journal.Order("local",1,"buy",state,"",0)); if(state=="rejected") s.setMeta("known_local_refusal:local","http_400"); val b=EngineTest.Fake()
   Engine(s,config(),b) { false }.step(event("replace")); assertEquals(1,b.posts); assertTrue(b.lookups.isEmpty())
  }
  for(state in listOf("unknown","rejected")) {
   val s=EngineTest.Store(); s.rev=Pair(2,false); s.os.add(Journal.Order("actual",1,"buy",state,"",0)); if(state=="unknown") s.setMeta("known_local_refusal:actual","http_400"); val b=EngineTest.Fake()
   Engine(s,config(),b) { false }.step(event("replace")); assertEquals(0,b.posts); assertEquals(listOf("actual"),b.lookups); assertFalse(s.done)
  }
 }
 @Test fun terminalRejectedOrCanceledExitIsRefreshedButNeverAutomaticallyRetried() {
  for(state in listOf("rejected","canceled")) {
   val s=EngineTest.Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("buy",1,"buy","filled","broker-buy",5)); s.os.add(Journal.Order("sell",2,"sell",state,"broker-sell",0)); s.setMeta("quantity:buy","5"); s.setMeta("quantity:sell","5"); val b=EngineTest.Fake()
   b.responses["buy"]=order(filled=5,state="filled"); b.responses["sell"]=order("sell","sell",0,5,state=state)
   Engine(s,config(),b) { true }.step(event()); assertEquals(0,b.posts); assertTrue(s.done); assertEquals(listOf("buy","sell"),b.lookups)
  }
 }
 @Test fun localRefusalMarkersNeverHideBrokerIdsOrFills() {
  for(record in listOf(Journal.Order("buy",1,"buy","superseded","broker-buy",0),Journal.Order("buy",1,"buy","superseded","",1),Journal.Order("buy",1,"buy","rejected","broker-buy",0))) {
   val s=EngineTest.Store(); s.rev=Pair(2,false); s.os.add(record); s.setMeta("known_local_refusal:buy","http_400"); val b=EngineTest.Fake()
   Engine(s,config(),b) { false }.step(event("replace")); assertEquals(0,b.posts); assertEquals(listOf("buy"),b.lookups); assertFalse(s.done)
  }
 }
 @Test fun failedTerminalLookupDoesNotPreventCancelOfAnotherFreshWorkingBuy() {
  for(fault in listOf("invalid_average","transport","missing")) {
   val s=EngineTest.Store(); s.rev=Pair(3,true); s.os.add(Journal.Order("old",1,"buy","canceled","broker-old",2)); s.os.add(Journal.Order("working",2,"buy","accepted","broker-working",0)); s.setMeta("quantity:old","5"); s.setMeta("quantity:working","3"); val b=EngineTest.Fake()
   b.responses["old"]=order("old",filled=2).put("filled_avg_price","-1"); b.responses["working"]=order("working",filled=0,qty=3,state="accepted")
   val transport=object:BrokerPort by b { override fun order(client:String):JSONObject? = if(client=="old" && fault=="transport") throw HttpError(503) else if(client=="old" && fault=="missing") null else b.order(client) }
   var now=Instant.now(); val engine=Engine(s,config(),transport,clock={now}) { true }; assertFalse(engine.reconcile(event("cancel",3))); assertEquals(0,b.canceled); val failure=runCatching { engine.step(event("cancel",3)) }; assertEquals(fault!="missing",failure.isFailure)
   assertEquals(fault,1,b.canceled); assertEquals(listOf("broker-working"),b.canceledIds); assertEquals("cancel_unknown",s.os.last().state); assertEquals(0,b.posts); assertFalse(engine.reconciliationHealthy)
   runCatching { engine.step(event("cancel",3)) }; assertEquals(1,b.canceled)
   now=now.plusSeconds(5); runCatching { engine.step(event("cancel",3)) }; assertEquals(2,b.canceled); assertTrue(b.canceledIds.all { it=="broker-working" }); assertEquals(0,b.posts)
  }
 }
 @Test fun failedWorkingLookupNeverCancelsItsCachedBrokerId() {
  val s=EngineTest.Store(); s.rev=Pair(2,true); s.os.add(Journal.Order("working",1,"buy","accepted","cached-id",0)); s.setMeta("quantity:working","5"); val b=EngineTest.Fake()
  Engine(s,config(),b) { true }.step(event("cancel")); assertEquals(0,b.canceled); assertEquals(0,b.posts); assertFalse(s.done)
 }
 @Test fun lifecycleFailuresAbortBeforeAnotherLookupOrCancellation() {
  for(failure in listOf(Superseded(),InterruptedException("Stopped"),java.util.concurrent.CancellationException("Canceled"))) {
   try {
    val s=EngineTest.Store(); s.rev=Pair(3,true); s.os.add(Journal.Order("old",1,"buy","canceled","broker-old",2)); s.os.add(Journal.Order("working",2,"buy","accepted","broker-working",0)); s.setMeta("quantity:old","5"); s.setMeta("quantity:working","3"); val b=EngineTest.Fake()
    b.responses["working"]=order("working",filled=0,qty=3,state="accepted")
    val stopped=object:BrokerPort by b { override fun order(client:String):JSONObject? { if(client=="old") throw failure; return b.order(client) } }
    assertThrows(failure.javaClass) { Engine(s,config(),stopped) { true }.step(event("cancel",3)) }
    assertTrue(b.lookups.isEmpty()); assertEquals(0,b.canceled); assertEquals(0,b.posts)
    if(failure is InterruptedException) assertTrue(Thread.currentThread().isInterrupted)
   } finally { Thread.interrupted() }
  }
 }
 @Test fun interruptionDuringACompletedLookupStillAbortsBeforeAnotherRowOrCancel() {
  try {
   val s=EngineTest.Store(); s.rev=Pair(3,true); s.os.add(Journal.Order("old",1,"buy","canceled","broker-old",2)); s.os.add(Journal.Order("working",2,"buy","accepted","broker-working",0)); s.setMeta("quantity:old","5"); s.setMeta("quantity:working","3"); val b=EngineTest.Fake()
   val stopped=object:BrokerPort by b { override fun order(client:String):JSONObject? { Thread.currentThread().interrupt(); return order("old",filled=2) } }
   assertThrows(InterruptedException::class.java) { Engine(s,config(),stopped) { true }.step(event("cancel",3)) }; assertTrue(Thread.currentThread().isInterrupted); assertTrue(b.lookups.isEmpty()); assertEquals(0,b.canceled)
  } finally { Thread.interrupted() }
 }
}

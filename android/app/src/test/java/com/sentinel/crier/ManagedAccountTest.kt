package com.sentinel.crier
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.time.Instant

class ManagedAccountTest {
 private val scope="alpaca:paper:account"
 private fun config()=JSONObject().put("account","account").put("environment","paper").put("role","follower")
 private fun event(id:String="event",trade:String="trade")=JSONObject().put("event_id",id).put("trade_id",trade).put("sequence",1).put("action","enter").put("symbol","SPY").put("asset","stock").put("environment","paper").put("quantity",5).put("limit_price","1.00").put("created_at",Instant.now().toString()).put("expires_at",Instant.now().plusSeconds(30).toString())
 private class Fake:BrokerPort {
  val base=EngineTest.Fake(); var stale=false; var timeout=false; var position=0; var options:String?=null; var inventory:Map<String,Int>?=null
  override fun account()=base.account()
  override fun order(client:String)=base.order(client)
  override fun cancel(id:String)=base.cancel(id)
  override fun holdings(symbol:String)=base.holdings(symbol)
  override fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean)=base.submit(event,client,quantity,sell,canSubmit)
  override fun binding(event:JSONObject)=JSONObject().put("account","account").put("environment","paper").put("currency","USD").put("symbol",event.getString("symbol")).put("asset",event.getString("asset")).put("multiplier",if(event.getString("asset")=="option") 100 else 1)
  override fun allocationFunds()=JSONObject().put("account","account").put("environment","paper").put("currency","USD").put("cash","100").put("equity","100").put("observed_at",Instant.now().minusSeconds(if(stale) 20 else 0).toString()).also { options?.let { value -> it.put("options_cash",value) } }
  override fun allocationPositions()=inventory ?: if(position==0) emptyMap() else mapOf("SPY" to position)
  override fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject {
   if(timeout) { if(!canSubmit()) throw Superseded(); base.posts++; throw java.net.SocketTimeoutException("synthetic uncertain POST") }
   return base.submit(event,client,quantity,sell,canSubmit)
  }
 }
 private fun bank():AccountBank=AccountBank(Files.createTempDirectory("managed-test").resolve("bank.json").toFile()).apply { enable(scope,"100","100",emptyMap()); for(r in listOf("alice","bob")) configure(scope,r,"stock","dollars","100","0") }
 @Test fun engineTimeoutCannotResubmitAcrossRestartOrAnotherRoute() {
  val b=bank(); val fake=Fake(); fake.timeout=true; val store=EngineTest.Store(); val e=event(); val c=config()
  val broker=ManagedAccount(b,scope,"alice",c,fake)
  assertThrows(java.net.SocketTimeoutException::class.java) { Engine(store,c,broker) { false }.step(e) }
  Engine(store,c,ManagedAccount(AccountBank(b.file),scope,"alice",c,fake)) { false }.step(e)
  assertEquals(1,fake.base.posts); assertEquals("unknown",b.orders(scope).single().getString("status"))
  Engine(EngineTest.Store(),c,ManagedAccount(b,scope,"bob",c,fake)) { false }.step(e)
  assertEquals(1,fake.base.posts)
 }
 @Test fun durableBankRefusalRepairsUnknownJournalAfterCrashWithoutBrokerLookup() {
  val b=bank(); val fake=Fake(); val e=event(); val c=config()
  val cid=b.reserve(scope,"alice",e,0,5,false,"1",1,"100","100")
  val store=EngineTest.Store(); store.setMeta("quantity:$cid","5"); store.unknown(cid,"trade",1,"buy")
  b.refuse(scope,cid) // Simulate process death before Engine can write the terminal journal state.
  val engine=Engine(store,c,ManagedAccount(AccountBank(b.file),scope,"alice",c,fake)) { false }
  engine.step(e)
  assertTrue(engine.reconciliationHealthy)
  assertEquals("superseded",store.orders("trade").single().state)
  assertFalse(fake.base.lookups.contains(cid)); assertEquals(0,fake.base.posts)
 }
 @Test fun staleFundsAndFinalPauseNeverPostAndRefusalReleasesReservation() {
  val b=bank(); val fake=Fake(); fake.stale=true; val c=config(); val e=event(); val broker=ManagedAccount(b,scope,"alice",c,fake)
  Engine(EngineTest.Store(),c,broker) { false }.step(e); assertEquals(0,fake.base.posts); assertEquals(0,b.orders(scope).size)
  fake.stale=false; fake.base.beforeSubmit={ throw Superseded() }
  Engine(EngineTest.Store(),c,broker) { false }.step(event("another","another")); assertEquals(0,fake.base.posts); assertEquals(0,"100".toBigDecimal().compareTo(b.report(scope).getString("available").toBigDecimal())); assertEquals("superseded",b.orders(scope).single().getString("status"))
 }
 @Test fun recoveryChecksRetiredOrdersAndCollectsIndependentFailures() {
  val b=bank(); val fake=Fake(); val e=event(); val cid=b.reserve(scope,"alice",e,0,5,false,"1",1,"100","100")
  b.refuse(scope,cid)
  val other=event("two","two"); val c2=b.reserve(scope,"alice",other,0,5,false,"1",1,"100","100")
  val result=ManagedAccount(b,scope,"alice",config(),fake,legacyCheck={ throw IllegalArgumentException("synthetic legacy") }).recovery()
  assertFalse(result.getBoolean("broker_checked")); assertEquals(2,result.getJSONArray("errors").length()); assertTrue(fake.base.lookups.contains(c2))
 }
 private fun option(id:String="option",trade:String="option")=event(id,trade).put("asset","option").put("symbol","SPY261120C00500000").put("limit_price","0.10")
 @Test fun stockUsesCommonCashWhileOptionBuyRequiresIndependentPositiveCapacity() {
  for(proof in listOf<String?>("0",null,"invalid")) {
   val b=bank(); b.configure(scope,"alice","option","units","10","0"); val fake=Fake(); fake.options=proof; val managed=ManagedAccount(b,scope,"alice",config(),fake)
   val stock=event(); managed.submit(stock,managed.clientOrderId(stock,0,false),2,false) { true }; assertEquals(1,fake.base.posts)
   val e=option(); assertThrows(Superseded::class.java) { managed.submit(e,managed.clientOrderId(e,0,false),1,false) { true } }; assertEquals(1,fake.base.posts)
  }
 }
 @Test fun optionAndStockReservationsDebitOneSharedCashLedger() {
  val b=bank(); b.configure(scope,"alice","option","units","10","0"); val fake=Fake(); fake.options="100"; val managed=ManagedAccount(b,scope,"alice",config(),fake)
  val stock=event(); managed.submit(stock,managed.clientOrderId(stock,0,false),40,false) { true }
  val opt=option().put("limit_price","0.50"); managed.submit(opt,managed.clientOrderId(opt,0,false),1,false) { true }
  val next=event("next","next"); assertThrows(Superseded::class.java) { managed.submit(next,managed.clientOrderId(next,0,false),11,false) { true } }
  assertEquals(2,fake.base.posts); assertEquals(0,"10".toBigDecimal().compareTo(b.report(scope).getString("available").toBigDecimal()))
 }
 @Test fun ownedOptionExitDoesNotRequireOptionsBuyingPower() {
  val b=bank(); b.configure(scope,"alice","option","units","10","0"); val fake=Fake(); fake.options="0"; val opt=option()
  val cid=b.reserve(scope,"alice",opt,0,1,false,"0.10",100,"100","100")
  val proof=JSONObject().put("id","owned-option").put("client_order_id",cid).put("symbol",opt.getString("symbol")).put("side","buy").put("qty","1").put("filled_qty","1").put("filled_avg_price","0.10").put("status","filled")
  b.observe(scope,cid,proof); fake.base.responses[cid]=proof; fake.inventory=mapOf(opt.getString("symbol") to 1)
  val managed=ManagedAccount(b,scope,"alice",config(),fake); val exit=option("exit").put("action","exit")
  managed.submit(exit,managed.clientOrderId(exit,0,true),1,true) { true }; assertEquals(1,fake.base.posts)
 }
}

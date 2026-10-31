package com.sentinel.crier

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class AccountBankTest {
 private fun bank()=AccountBank(Files.createTempDirectory("synthetic-bank").resolve("bank.json").toFile())
 private val scope="alpaca:paper:synthetic"
 private fun event(trade:String="t",id:String="e")=JSONObject().put("trade_id",trade).put("event_id",id).put("symbol","SPY").put("asset","stock").put("environment","paper")
 private fun proof(cid:String,qty:Int,filled:Int,status:String="filled",price:String="10")=JSONObject().put("id","broker-$cid").put("client_order_id",cid).put("symbol","SPY").put("side","buy").put("qty",qty.toString()).put("filled_qty",filled.toString()).put("filled_avg_price",price).put("status",status)
 @Test fun timeoutReservationSurvivesRestartAndCannotDispatchAgain() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); b.configure(scope,"alice","stock","dollars","100","0")
  b.configure(scope,"bob","stock","dollars","100","0")
  val cid=b.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100")
  val reopened=AccountBank(b.file)
  assertEquals(1,reopened.report(scope).getJSONArray("active").length())
  assertThrows(IllegalArgumentException::class.java) { reopened.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100") }
  assertThrows(IllegalArgumentException::class.java) { reopened.reserve(scope,"bob",event("other","other"),0,9,false,"10",1,"100","100") }
  assertEquals(cid,reopened.orders(scope).single().getString("cid"))
 }
 @Test fun competingRoutesCannotReserveTheSameCash() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); for(r in listOf("alice","bob")) b.configure(scope,r,"stock","dollars","100","0")
  val start=java.util.concurrent.CountDownLatch(1); val won=java.util.concurrent.atomic.AtomicInteger(); val threads=listOf("alice","bob").map { route -> Thread { start.await(); try { AccountBank(b.file).reserve(scope,route,event(route,route),0,6,false,"10",1,"100","100"); won.incrementAndGet() } catch(_:IllegalArgumentException) {} }.apply { start() } }
  start.countDown(); threads.forEach { it.join() }; assertEquals(1,won.get()); assertEquals("40",b.report(scope).getString("available"))
 }
 @Test fun negativeCashCapacityStaysBlockedUntilVerifiedFlatRebase() {
  val b=bank(); b.enable(scope,"20","20",emptyMap()); for(r in listOf("alice","bob")) b.configure(scope,r,"stock","dollars","20","0")
  val cid=b.reserve(scope,"alice",event(),0,2,false,"10",1,"20","20"); b.observe(scope,cid,proof(cid,2,0,"canceled"))
  b.reserve(scope,"bob",event("other","other"),0,2,false,"10",1,"20","20")
  b.observe(scope,cid,proof(cid,2,1,"canceled"))
  assertEquals("-10",b.report(scope).getString("available")); b.refreshFlatFunds(scope,"100","100")
  assertEquals("-10",b.report(scope).getString("available")); assertTrue(b.report(scope).getString("blocked").isNotBlank())
 }
 @Test fun retiredOriginalClientIsRetainedAndLateFillPermanentlyBlocks() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); b.configure(scope,"alice","stock","units","10","0")
  val cid=b.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100"); b.observe(scope,cid,proof(cid,2,0,"canceled"))
  assertEquals(0,b.report(scope).getJSONArray("active").length()); assertEquals(1,b.report(scope).getJSONArray("archived").length())
  b.observe(scope,cid,proof(cid,2,1,"canceled"))
  assertEquals(1,b.report(scope).getJSONArray("active").getJSONObject(0).getInt("units"))
  b.inventory(scope,mapOf("SPY" to 1)); assertTrue(b.report(scope).getString("blocked").isNotBlank())
 }
 @Test fun profitsNeverExpandSharedCashCapacityAndExecutionMustRespectLimit() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); b.configure(scope,"alice","stock","dollars","100","0")
  val buy=b.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100"); b.observe(scope,buy,proof(buy,2,2))
  val sell=b.reserve(scope,"alice",event(id="sell"),0,2,true,"11",1,"100","100"); b.observe(scope,sell,proof(sell,2,2,price="12").put("side","sell"))
  assertEquals(0,"100".toBigDecimal().compareTo(b.report(scope).getString("available").toBigDecimal()))
  val other=b.reserve(scope,"alice",event("other","other"),0,2,false,"10",1,"100","100")
  assertThrows(IllegalArgumentException::class.java) { b.observe(scope,other,proof(other,2,2,price="11")) }
 }
 @Test fun filledStatusRequiresAllRequestedUnits() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); b.configure(scope,"alice","stock","units","10","0")
  val cid=b.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100")
  assertThrows(IllegalArgumentException::class.java) { b.observe(scope,cid,proof(cid,2,1)) }
 }
 @Test fun ordinaryRefreshCannotClearConflictButVerifiedFlatRepairPreservesTombstones() {
  val b=bank(); b.enable(scope,"100","100",emptyMap()); b.configure(scope,"alice","stock","units","10","0")
  val cid=b.reserve(scope,"alice",event(),0,2,false,"10",1,"100","100"); b.observe(scope,cid,proof(cid,2,0,"canceled"))
  assertThrows(IllegalArgumentException::class.java) { b.observe(scope,cid,proof(cid,2,0,"new")) }
  b.refreshFlatFunds(scope,"200","200"); assertTrue(b.report(scope).getString("blocked").isNotBlank())
  b.inventory(scope,emptyMap()); b.repairVerifiedFlat(scope,"200","200")
  val audit=JSONObject(b.file.readText()).getJSONObject("accounts").getJSONObject(scope).getJSONArray("audit")
  val repair=(0 until audit.length()).map { audit.getJSONObject(it) }.single { it.optString("kind")=="verified_flat_repair" }
  assertTrue(repair.getString("prior_block").isNotBlank()); assertEquals("200",repair.getString("cash")); assertEquals("200",repair.getString("equity")); assertTrue(repair.getJSONArray("retained_ids").length()>0); java.time.Instant.parse(repair.getString("at"))
  assertEquals("",b.report(scope).getString("blocked")); assertEquals(1,b.report(scope).getJSONArray("archived").length()); assertEquals(cid,b.orders(scope).single().getString("cid"))
  assertThrows(IllegalArgumentException::class.java) { b.reserve(scope,"alice",event(id="replay"),0,1,false,"10",1,"200","200") }
 }
 @Test fun partialCanceledFillRetainsOwnershipAndExitCannotBorrowAnotherHost() {
  val b=bank(); b.enable(scope,"1000","1000",emptyMap()); for(r in listOf("alice","bob")) b.configure(scope,r,"stock","units","10","0")
  val a=b.reserve(scope,"alice",event(),0,5,false,"10",1,"1000","1000"); b.observe(scope,a,proof(a,5,2,"canceled"))
  val bob=b.reserve(scope,"bob",event("other","other"),0,5,false,"10",1,"1000","1000"); b.observe(scope,bob,proof(bob,5,5))
  assertThrows(IllegalArgumentException::class.java) { b.reserve(scope,"alice",event(id="exit"),0,3,true,"10",1,"1000","1000") }
  val sell=b.reserve(scope,"alice",event(id="exit"),0,2,true,"10",1,"1000","1000")
  assertThrows(IllegalArgumentException::class.java) { b.reserve(scope,"alice",event(id="exit2"),0,1,true,"10",1,"1000","1000") }
  b.observe(scope,sell,proof(sell,2,2).put("side","sell")); b.invalidate(scope,"alice","t")
  assertEquals(1,b.report(scope).getJSONArray("active").length())
  assertThrows(IllegalArgumentException::class.java) { b.reserve(scope,"alice",event(id="replay"),0,1,false,"10",1,"1000","1000") }
 }
 @Test fun duplicateSourceAcrossRoutesAndInventoryMismatchBlockAdmission() {
  val b=bank(); b.enable(scope,"1000","1000",mapOf("SPY" to 4)); for(r in listOf("alice","bob")) b.configure(scope,r,"stock","equity_percent","50","0")
  val a=b.reserve(scope,"alice",event(),0,1,false,"10",1,"1000","1000"); b.observe(scope,a,proof(a,1,1))
  assertThrows(IllegalArgumentException::class.java) { b.reserve(scope,"bob",event(),0,1,false,"10",1,"1000","1000") }
  assertThrows(IllegalArgumentException::class.java) { b.inventory(scope,mapOf("SPY" to 4)) }
  assertTrue(b.report(scope).getString("blocked").isNotEmpty())
  b.inventory(scope,mapOf("SPY" to 5)); assertEquals("",b.report(scope).getString("blocked"))
 }
}

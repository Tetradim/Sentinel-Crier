package com.sentinel.crier

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import android.content.Context
import android.content.ContextWrapper
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.Instant

/** Native storage/Keystore/SQLite integration. Only synthetic broker methods are reachable. */
@RunWith(AndroidJUnit4::class)
class AccountBankPersistenceTest {
 private fun isolated():Context {
  val app=ApplicationProvider.getApplicationContext<Context>(); val id="bank-test-${java.util.UUID.randomUUID()}"; val dir=File(app.filesDir,id).apply { mkdirs() }
  return object:ContextWrapper(app) {
   override fun getApplicationContext():Context=this
   override fun getFilesDir():File=dir
   override fun getDatabasePath(name:String):File=File(dir,name)
   override fun getSharedPreferences(name:String,mode:Int)=app.getSharedPreferences("$id-$name",mode)
  }
 }
 private class Synthetic:BrokerPort {
  val responses=mutableMapOf<String,JSONObject>(); var posts=0
  override fun account()="synthetic"
  override fun allocationFunds()=JSONObject().put("account","synthetic").put("environment","paper").put("currency","USD").put("cash","100").put("equity","100").put("observed_at",Instant.now().toString())
  override fun allocationPositions()=emptyMap<String,Int>()
  override fun binding(event:JSONObject)=JSONObject().put("account","synthetic").put("environment","paper").put("currency","USD").put("symbol","SPY").put("asset","stock").put("multiplier",1)
  override fun order(client:String)=responses[client]
  override fun cancel(id:String) { throw AssertionError("No cancellation expected") }
  override fun holdings(symbol:String)=0
  override fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean):JSONObject=throw AssertionError("Only checked synthetic submit expected")
  override fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject {
   check(canSubmit()); posts++
   return JSONObject().put("id","synthetic-broker-$client").put("client_order_id",client).put("symbol","SPY").put("side","buy").put("qty",quantity.toString()).put("filled_qty","0").put("status","accepted").also { responses[client]=it }
  }
 }
 @Test fun productionManagedFactoryUsesOneReentrantBankDuringLegacyScanAndPersistsReservation() {
  val context=isolated(); val config=JSONObject().put("account","synthetic").put("environment","paper").put("role","follower"); val raw=Synthetic(); val bank=AndroidAccountBank.bank(context); val scope=RouteAccounts.key(config)
  bank.enable(scope,"100","100",emptyMap()); bank.configure(scope,"legacy","stock","dollars","100","0")
  val managed=AndroidAccountBank.managed(context,"legacy",config,raw)
  val event=JSONObject().put("event_id","synthetic-event").put("trade_id","synthetic-trade").put("symbol","SPY").put("asset","stock").put("environment","paper")
  val cid=managed.clientOrderId(event,0,false); managed.submit(event.put("limit_price","1"),cid,2,false) { true }
  assertEquals(1,raw.posts); assertEquals(cid,AndroidAccountBank.bank(context).orders(scope).single().getString("cid")); assertTrue(managed.recovery().getBoolean("broker_checked"))
 }
 @Test fun setupBarrierRejectsConcurrentStartsAndAlwaysReleasesAfterFailure() {
  val context=isolated()
  SyncService.withBankTransition {
   assertThrows(IllegalStateException::class.java) { SyncService.requestStart(context) }
   assertThrows(IllegalStateException::class.java) { SyncService.withBankTransition { fail("Nested transition") } }
  }
  assertThrows(IllegalArgumentException::class.java) { SyncService.withBankTransition { throw IllegalArgumentException("synthetic") } }
  assertEquals("released",SyncService.withBankTransition { "released" })
 }
 @Test fun nativeLegacyMigrationRefusesPartiallyCanceledHoldingsUntilOriginalExitIsVerified() {
  val context=isolated(); val config=JSONObject().put("account","synthetic").put("environment","paper").put("role","follower")
  Vault(context).save(config); val saved=Vault(context).read(); val raw=Synthetic()
  val db=android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(Settings.journalName(saved)),null)
  db.use {
   it.execSQL("CREATE TABLE orders(client TEXT,trade TEXT,seq INTEGER,side TEXT,state TEXT,broker TEXT,filled INTEGER)")
   it.execSQL("CREATE TABLE events(trade TEXT,seq INTEGER,payload TEXT)")
   it.execSQL("CREATE TABLE meta(k TEXT,v TEXT)")
   it.execSQL("INSERT INTO orders VALUES('old-buy','old-trade',1,'buy','canceled','old-buy-broker',2)")
   it.execSQL("INSERT INTO events VALUES('old-trade',1,?)",arrayOf(JSONObject().put("symbol","SPY").toString()))
   it.execSQL("INSERT INTO meta VALUES('quantity:old-buy','5')")
  }
  raw.responses["old-buy"]=JSONObject().put("client_order_id","old-buy").put("id","old-buy-broker").put("symbol","SPY").put("side","buy").put("qty","5").put("filled_qty","2").put("status","canceled")
  assertThrows(IllegalArgumentException::class.java) { AndroidAccountBank.verifyLegacy(context,saved,raw) }
  android.database.sqlite.SQLiteDatabase.openDatabase(context.getDatabasePath(Settings.journalName(saved)).path,null,0).use {
   it.execSQL("INSERT INTO orders VALUES('old-sell','old-trade',2,'sell','filled','old-sell-broker',2)")
   it.execSQL("INSERT INTO events VALUES('old-trade',2,?)",arrayOf(JSONObject().put("symbol","SPY").toString()))
   it.execSQL("INSERT INTO meta VALUES('quantity:old-sell','2')")
  }
  raw.responses["old-sell"]=JSONObject().put("client_order_id","old-sell").put("id","old-sell-broker").put("symbol","SPY").put("side","sell").put("qty","2").put("filled_qty","2").put("status","filled")
  AndroidAccountBank.verifyLegacy(context,saved,raw); assertEquals(0,raw.posts)
 }
}

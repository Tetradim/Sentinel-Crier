package com.sentinel.crier

import android.content.Context
import org.json.JSONObject
import java.io.File

/** Keeps the installation ledger outside route journals. No credentials enter this file. */
object AndroidAccountBank {
 fun bank(context:Context)=AccountBank(File(context.applicationContext.filesDir,"account-id-bank.json"))
 fun enabled(context:Context,config:JSONObject)=config.has("account") && bank(context).enabled(RouteAccounts.key(config))
 fun pauseRoutes(context:Context,config:JSONObject,all:Boolean=false) {
  val scope=RouteAccounts.key(config)
  for(p in Vault(context.applicationContext).profiles()) {
   val saved=p.getJSONObject("config")
   if(all || (saved.has("account") && RouteAccounts.key(saved)==scope)) check(context.applicationContext.getSharedPreferences(RouteStorage.preferences("controls",p.getString("id")),Context.MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit())
  }
 }
 fun managed(context:Context,route:String,config:JSONObject,broker:BrokerPort):ManagedAccount {
  val b=bank(context); val scope=RouteAccounts.key(config)
  return ManagedAccount(b,scope,route,config,broker,{ undispatched -> verifyLegacy(context,config,broker,undispatched,b) })
 }
 /** Reads every retained journal for this destination, never adopts old lots or orders. */
 fun verifyLegacy(context:Context,config:JSONObject,broker:BrokerPort,undispatched:String?=null,b:AccountBank=bank(context)) {
  val scope=RouteAccounts.key(config); val registered=if(b.enabled(scope)) b.orders(scope).associateBy { it.getString("cid") } else emptyMap()
  val profiles=Vault(context.applicationContext).profiles().filter { it.getJSONObject("config").has("account") && RouteAccounts.key(it.getJSONObject("config"))==scope }
  for(profile in profiles) {
   val saved=profile.getJSONObject("config"); val route=profile.getString("id"); val path=context.getDatabasePath(Settings.journalName(saved))
   if(!path.exists()) continue
   android.database.sqlite.SQLiteDatabase.openDatabase(path.path,null,android.database.sqlite.SQLiteDatabase.OPEN_READONLY).use { db ->
    val quantities=mutableMapOf<String,Int>()
    db.rawQuery("SELECT o.client,o.trade,o.seq,o.side,o.state,o.broker,o.filled,e.payload FROM orders o JOIN events e ON e.trade=o.trade AND e.seq=o.seq",null).use { c ->
     while(c.moveToNext()) {
      val cid=c.getString(0); val state=c.getString(4); val localBroker=c.getString(5); val localFill=c.getInt(6)
      if(localBroker.isBlank() && localFill==0 && state in setOf("superseded","rejected")) continue
      if(cid.startsWith("sc-")) {
       if(cid==undispatched && localBroker.isBlank() && localFill==0 && registered[cid]==null) continue
       val order=registered[cid] ?: throw IllegalArgumentException("Managed journal order missing from account bank")
       val report=b.report(scope); val all=report.getJSONArray("active").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }+report.getJSONArray("archived").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
       require(all.single { it.getInt("id")==order.getInt("bank_id") }.getString("route")==route) { "Managed order belongs to another original route" }
       continue
      }
      val e=JSONObject(c.getString(7)); val proof=broker.order(cid) ?: throw IllegalArgumentException("Legacy broker outcome unknown; retain original route")
      val qty=db.rawQuery("SELECT v FROM meta WHERE k=?",arrayOf("quantity:$cid")).use { q -> require(q.moveToFirst()); q.getString(0).toBigDecimal() }
      val filled=proof.getString("filled_qty").toBigDecimal().intValueExact()
      require(proof.getString("client_order_id")==cid && proof.getString("symbol")==e.getString("symbol") && proof.getString("side")==c.getString(3) && proof.getString("qty").toBigDecimal()==qty && proof.getString("status") in AccountBank.terminal && proof.getString("id").isNotBlank() && (localBroker.isBlank() || localBroker==proof.getString("id")) && filled>=localFill && filled.toBigDecimal()<=qty) { "Legacy order unresolved or contradictory; recover original route first" }
      val trade=c.getString(1); quantities[trade]=(quantities[trade] ?: 0)+filled*(if(c.getString(3)=="buy") 1 else -1)
     }
    }
    require(quantities.values.all { it==0 }) { "Close and reconcile legacy Crier lots before enabling the account bank" }
   }
  }
 }
 fun setup(context:Context,config:JSONObject):String=SyncService.withBankTransition(beforeCheck={ pauseRoutes(context,config,true) }) {
  require(config.has("account") && config.optString("mode","exact_limit")!="market") { "Verify the account and select limit pricing first" }
  val broker=Broker(config); require(broker.account()==config.getString("account"))
  val b=bank(context); val scope=RouteAccounts.key(config)
  b.locked { verifyLegacy(context,config,broker,b=b); val f=broker.allocationFunds(); val positions=broker.allocationPositions(); b.enable(scope,f.getString("cash"),f.getString("equity"),positions); b.inventory(scope,positions) }
  "Account bank enabled. All connections remain stopped and paused. Save each host's pools (default zero), then explicitly reconnect."
 }
}

package com.sentinel.crier

import org.json.JSONObject
import java.time.Duration
import java.time.Instant

/** Production dispatch adapter. Bank locking covers reads, reservation and exactly one POST. */
class ManagedAccount(private val bank:AccountBank,private val scope:String,private val route:String,private val config:JSONObject,private val broker:BrokerPort,private val legacyCheck:(String?)->Unit={},private val clock:()->Instant={Instant.now()}):BrokerPort by broker {
 init { require(RouteAccounts.key(config)==scope && bank.enabled(scope)) }
 override fun clientOrderId(event:JSONObject,ordinal:Int,sell:Boolean)=AccountBank.client(scope,route,event,ordinal,sell)
 override fun observeIntent(event:JSONObject) { if(event.getString("action") in setOf("cancel","exit")) bank.invalidate(scope,route,event.getString("trade_id")) }
 private fun funds():JSONObject {
  require(broker.account()==config.getString("account")) { "Pinned account changed" }
  val f=broker.allocationFunds(); val age=Duration.between(Instant.parse(f.getString("observed_at")),clock()).toMillis()
  require(f.getString("account")==config.getString("account") && f.getString("environment")==config.getString("environment") && f.getString("currency")=="USD" && age in 0..10000) { "Fresh pinned USD funds required" }
  AccountBank.amount(f.getString("cash")); require(AccountBank.amount(f.getString("equity"))>java.math.BigDecimal.ZERO); return f
 }
 override fun locallyRefused(client:String):Boolean=bank.locked {
  val order=bank.orders(scope).singleOrNull { it.getString("cid")==client } ?: return@locked false
  require(bank.ownedOrder(scope,route,client)) { "Order belongs to another original host route" }
  order.getString("status")=="superseded" && order.getInt("filled")==0 && order.getString("broker").isEmpty()
 }
 override fun order(client:String):JSONObject?=bank.locked {
  val registered=bank.orders(scope).any { it.getString("cid")==client }
  if(!registered) { require(!client.startsWith("sc-")) { "Managed client ID missing from bank" }; return@locked broker.order(client) }
  require(bank.ownedOrder(scope,route,client)) { "Order belongs to another original host route" }
  broker.order(client)?.also { bank.observe(scope,client,it) }
 }
 override fun cancel(id:String)=bank.locked {
  require(bank.orders(scope).count { it.getString("broker")==id && bank.ownedOrder(scope,route,it.getString("cid")) }==1) { "Cancellation belongs to another original host route" }
  broker.cancel(id)
 }
 private fun reconcile(undispatched:String?=null) {
  legacyCheck(undispatched)
  // Terminal and retired IDs remain observable: a late fill must never disappear from recovery.
  for(o in bank.orders(scope)) {
   if(o.getString("status")=="superseded") continue
   val p=broker.order(o.getString("cid")) ?: throw IllegalArgumentException("Unresolved broker outcome; original reservation retained")
   bank.observe(scope,o.getString("cid"),p)
  }
  bank.inventory(scope,broker.allocationPositions())
 }
 fun recovery():JSONObject=bank.locked {
  val errors=org.json.JSONArray()
  try { require(broker.account()==config.getString("account")) } catch(_:Exception) { errors.put("Pinned account verification failed") }
  try { legacyCheck(null) } catch(_:Exception) { errors.put("Legacy journal needs recovery through original route") }
  for(o in bank.orders(scope)) {
   if(o.getString("status")=="superseded") continue
   try { val snapshot=broker.order(o.getString("cid")) ?: throw IllegalArgumentException(); bank.observe(scope,o.getString("cid"),snapshot) }
   catch(_:Exception) { errors.put("Inspect original client ID ${o.getString("cid")}; reservation retained") }
  }
  var positions:Map<String,Int>?=null
  try { positions=broker.allocationPositions(); bank.inventory(scope,positions) } catch(_:Exception) { errors.put("Account inventory unavailable or differs from retained ownership") }
  val report=bank.report(scope)
  val comparison=org.json.JSONArray(); val owned=mutableMapOf<String,Int>(); val active=report.getJSONArray("active"); for(i in 0 until active.length()) { val row=active.getJSONObject(i); val symbol=row.getString("symbol"); owned[symbol]=(owned[symbol] ?: 0)+row.getInt("units") }
  val baseline=report.getJSONObject("baseline"); val symbols=owned.keys+baseline.keys().asSequence().toSet()+(positions?.keys ?: emptySet())
  for(symbol in symbols.sorted()) { val expected=(owned[symbol] ?: 0)+baseline.optInt(symbol,0); comparison.put(JSONObject().put("symbol",symbol).put("host_owned",owned[symbol] ?: 0).put("external_baseline",baseline.optInt(symbol,0)).put("expected",expected).put("broker",positions?.get(symbol) ?: if(positions==null) JSONObject.NULL else 0).put("difference",if(positions==null) JSONObject.NULL else (positions[symbol] ?: 0)-expected)) }
  report.put("errors",errors).put("positions",comparison).put("broker_positions",positions?.let { JSONObject(it) } ?: JSONObject.NULL).put("broker_checked",errors.length()==0 && report.getString("blocked").isEmpty()).put("checked_at",clock().toString())
 }
 fun repairFlat():JSONObject=bank.locked {
  val check=recovery()
  require(check.getJSONArray("errors").length()==0) { "Resolve every broker, journal and inventory check before flat repair" }
  val f=funds(); bank.repairVerifiedFlat(scope,f.getString("cash"),f.getString("equity")); bank.report(scope)
 }
 override fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean):JSONObject {
  val price=Policy.price(event.getString("limit_price"),config.optString("mode","exact_limit"),sell,config.optInt("bps",100),config.optString("amount","0.02")) ?: throw Superseded()
  return dispatch(event,client,quantity,sell,JSONObject().put("binding",broker.binding(event)).put("price",price),canSubmit)
 }
 override fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean)=dispatch(event,client,quantity,sell,plan,canSubmit)
 private fun dispatch(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject=bank.locked {
  var reserved=false
  try {
   require(!plan.isNull("price")) { "Shared bank requires a bounded limit" }
   val binding=broker.binding(event); val pinned=plan.getJSONObject("binding")
   require(listOf("account","environment","symbol","asset","currency","multiplier").all { binding.get(it).toString()==pinned.get(it).toString() }) { "Instrument binding changed" }
   require(binding.getString("account")==config.getString("account") && binding.getString("environment")==config.getString("environment") && binding.getString("symbol")==event.getString("symbol") && binding.getString("asset")==event.getString("asset") && binding.getString("currency")=="USD")
   val ordinal=(0..1000).singleOrNull { clientOrderId(event,it,sell)==client } ?: throw IllegalArgumentException("Client identity mismatch")
   reconcile(client); val f=funds(); bank.refreshFlatFunds(scope,f.getString("cash"),f.getString("equity"))
   val admissionCash=if(!sell && event.getString("asset")=="option") AccountBank.amount(f.getString("cash")).min(AccountBank.amount(f.getString("options_cash"))).toPlainString() else f.getString("cash")
   if(!canSubmit()) throw Superseded()
   require(bank.reserve(scope,route,event,ordinal,quantity,sell,plan.getString("price"),binding.getInt("multiplier"),admissionCash,f.getString("equity"))==client); reserved=true
   val result=broker.submitPlanned(event,client,quantity,sell,plan) { Duration.between(Instant.parse(f.getString("observed_at")),clock()).toMillis() in 0..10000 && canSubmit() }
   bank.observe(scope,client,result); result
  } catch(e:Superseded) { if(reserved) bank.refuse(scope,client); throw e }
  catch(e:HttpError) { if(reserved && e.status in setOf(400,401,403)) bank.refuse(scope,client); throw e }
  catch(e:Exception) { if(!reserved && e !is InterruptedException) throw Superseded(); throw e }
 }
}

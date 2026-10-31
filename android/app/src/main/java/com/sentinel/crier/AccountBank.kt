package com.sentinel.crier

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.math.BigDecimal
import java.math.RoundingMode
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** Installation-wide durable ledger. Reservations and tombstones are committed before POST.
 * The lock is held across reconciliation and dispatch, including between different routes.
 * A failed/unknown POST never removes its reservation or permits another dispatch.
 */
class AccountBank(val file:File) {
 companion object {
  private val monitors=java.util.concurrent.ConcurrentHashMap<String,Any>()
  val terminal=setOf("filled","canceled","expired","rejected","replaced","superseded")
  private val statuses=terminal+setOf("unknown","new","accepted","pending_new","accepted_for_bidding","partially_filled","done_for_day","pending_cancel","pending_replace","stopped","suspended","calculated")
  fun amount(text:String):BigDecimal { require(text.length<=24 && text.matches(Regex("(?:0|[1-9][0-9]*)(?:\\.[0-9]{1,8})?"))) { "Canonical nonnegative decimal required" }; return text.toBigDecimal() }
  private fun digest(text:String)=MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
  fun client(scope:String,route:String,event:JSONObject,ordinal:Int,sell:Boolean):String="sc-"+digest(JSONArray(listOf(scope,route,event.getString("trade_id"),event.getString("event_id"),if(sell) "sell" else "buy",ordinal)).toString()).take(40)
  private fun rows(array:JSONArray)=(0 until array.length()).map { array.getJSONObject(it) }
 }
 private val held=ThreadLocal<JSONObject?>()
 /** Reentrant process monitor plus OS lock, so account preflight and POST cannot interleave. */
 fun <T> locked(action:()->T):T=synchronized(monitors.getOrPut(file.canonicalPath) { Any() }) {
  if(held.get()!=null) return@synchronized action()
  file.parentFile!!.mkdirs()
  RandomAccessFile(File(file.path+".lock"),"rw").use { lockFile -> lockFile.channel.lock().use {
   val root=if(file.exists()) JSONObject(file.readText()) else JSONObject().put("version",1).put("next",1).put("accounts",JSONObject())
   require(root.getInt("version")==1) { "Unsupported bank schema; preserve bank and journals" }
   held.set(root)
   try { action() } finally { held.remove() }
  } }
 }
 private fun root()=held.get() ?: error("Bank lock required")
 private fun save() {
  val temp=File(file.path+".new")
  java.io.FileOutputStream(temp).use { out -> out.write(root().toString().toByteArray(Charsets.UTF_8)); out.fd.sync() }
  Files.move(temp.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING)
 }
 private fun account(scope:String)=root().getJSONObject("accounts").getJSONObject(scope)
 // Atomic rename makes a lock-free enable check safe while the encrypted vault is locked.
 // Taking the bank lock from Vault.save would invert dispatch's bank -> vault lock order.
 fun enabled(scope:String):Boolean {
  val document=held.get() ?: if(file.exists()) JSONObject(file.readText()) else return false
  require(document.getInt("version")==1) { "Unsupported bank schema; preserve bank and journals" }
  return document.getJSONObject("accounts").has(scope)
 }
 fun enable(scope:String,cash:String,equity:String,baseline:Map<String,Int>)=locked {
  require(amount(equity)>BigDecimal.ZERO && baseline.values.all { it>=0 })
  if(!root().getJSONObject("accounts").has(scope)) {
   root().getJSONObject("accounts").put(scope,JSONObject().put("available",amount(cash).min(amount(equity)).toPlainString()).put("blocked","").put("baseline",JSONObject(baseline)).put("policies",JSONObject()).put("lots",JSONArray()).put("orders",JSONArray()))
   save()
  }
 }
 fun configure(scope:String,route:String,asset:String,mode:String,value:String,fee:String)=locked {
  require(route.isNotBlank() && asset in setOf("stock","option") && mode in setOf("units","dollars","equity_percent")); val v=amount(value); amount(fee)
  require(mode!="equity_percent" || v<=BigDecimal(100)); require(mode!="units" || (v.stripTrailingZeros().scale()<=0 && v<=BigDecimal(1000000000)))
  account(scope).getJSONObject("policies").put("$route:$asset",JSONObject().put("mode",mode).put("value",value).put("fee",fee)); save()
 }
 fun orders(scope:String):List<JSONObject> = locked { rows(account(scope).getJSONArray("orders")).map { JSONObject(it.toString()) } }
 fun ownedOrder(scope:String,route:String,cid:String):Boolean=locked {
  val a=account(scope); val o=rows(a.getJSONArray("orders")).singleOrNull { it.getString("cid")==cid } ?: return@locked false
  rows(a.getJSONArray("lots")).single { it.getInt("id")==o.getInt("bank_id") }.getString("route")==route
 }
 private fun ordersFor(a:JSONObject,l:JSONObject)=rows(a.getJSONArray("orders")).filter { it.getInt("bank_id")==l.getInt("id") }
 private fun units(a:JSONObject,l:JSONObject)=ordersFor(a,l).sumOf { it.getInt("filled")*(if(it.getString("side")=="buy") 1 else -1) }
 private fun pending(a:JSONObject,l:JSONObject,side:String)=ordersFor(a,l).filter { it.getString("side")==side && it.getString("status") !in terminal }.sumOf { it.getInt("quantity")-it.getInt("filled") }
 private fun basis(a:JSONObject,l:JSONObject)=ordersFor(a,l).fold(BigDecimal.ZERO) { total,o -> total+if(o.getString("side")=="buy") o.getString("cost").toBigDecimal() else -o.getString("basis").toBigDecimal() }
 private fun exposure(a:JSONObject,l:JSONObject)=ordersFor(a,l).fold(BigDecimal.ZERO) { total,o -> total+if(o.getString("side")=="buy") o.getString("charge").toBigDecimal()-o.getString("booked_fee").toBigDecimal() else -o.getString("basis").toBigDecimal() }.max(BigDecimal.ZERO)
 private fun retire(a:JSONObject,l:JSONObject) {
  if(units(a,l)==0 && ordersFor(a,l).all { it.getString("status") in terminal }) l.put("active",false)
 }
 fun invalidate(scope:String,route:String,trade:String)=locked {
  val a=account(scope); rows(a.getJSONArray("lots")).filter { it.getString("route")==route && it.getString("trade")==trade }.forEach { it.put("invalid",true); retire(a,it) }; save()
 }
 fun refuse(scope:String,cid:String)=locked {
  val a=account(scope); val o=rows(a.getJSONArray("orders")).single { it.getString("cid")==cid }
  require(o.getString("status")=="unknown" && o.getInt("filled")==0 && o.getString("broker").isEmpty())
  if(o.getString("side")=="buy") a.put("available",(a.getString("available").toBigDecimal()+o.getString("charge").toBigDecimal()).toPlainString())
  o.put("status","superseded").put("charge","0"); rows(a.getJSONArray("lots")).single { it.getInt("id")==o.getInt("bank_id") }.also { retire(a,it) }; save()
 }
 fun reserve(scope:String,route:String,event:JSONObject,ordinal:Int,quantity:Int,sell:Boolean,price:String,multiplier:Int,cash:String,equity:String):String=locked {
  val a=account(scope); require(sell || a.getString("blocked").isEmpty()) { "Account bank blocked: ${a.getString("blocked")}" }
  require(quantity in 1..1000 && ordinal>=0 && event.getString("environment")==scope.split(":")[1])
  val asset=event.getString("asset"); require(asset in setOf("stock","option") && multiplier==if(asset=="option") 100 else 1)
  val p=amount(price); require(p>BigDecimal.ZERO)
  val cid=client(scope,route,event,ordinal,sell); val os=rows(a.getJSONArray("orders"))
  require(os.none { it.getString("cid")==cid || (it.getString("event")==event.getString("event_id") && it.getString("side")== (if(sell) "sell" else "buy") && it.getInt("ordinal")==ordinal) }) { "Order already reserved; inspect original client ID" }
  val lots=rows(a.getJSONArray("lots")); val trade=event.getString("trade_id")
  require(lots.none { it.getString("trade")==trade && it.getString("route")!=route }) { "Source trade already owned by another host" }
  var lot=lots.singleOrNull { it.getString("route")==route && it.getString("trade")==trade }
  if(lot!=null) require(lot.getBoolean("active") && (sell || !lot.getBoolean("invalid")) && lot.getString("symbol")==event.getString("symbol") && lot.getString("asset")==asset && lot.getInt("multiplier")==multiplier) { "Immutable or retired trade ownership" }
  val policy=a.getJSONObject("policies").optJSONObject("$route:$asset") ?: JSONObject().put("mode","dollars").put("value","0").put("fee","0")
  val fee=amount(policy.getString("fee")); val charge=if(sell) BigDecimal.ZERO else p*multiplier.toBigDecimal()*quantity.toBigDecimal()+fee
  if(sell) { require(lot!=null && quantity<=units(a,lot)-pending(a,lot,"sell")) { "Exit exceeds this host's unreserved owned units" }; require(fee<=p*multiplier.toBigDecimal()) { "Exit limit cannot cover fee reserve" } }
  else {
   val local=a.getString("available").toBigDecimal(); require(charge<=local.min(amount(cash)).min(amount(equity))) { "Account cash capacity exceeded" }
   val host=lots.filter { it.getString("route")==route && it.getString("asset")==asset }
   val used=host.fold(BigDecimal.ZERO) { n,l -> n+exposure(a,l) }
   val losses=host.fold(BigDecimal.ZERO) { n,l -> n+ordersFor(a,l).filter { it.getString("side")=="sell" }.fold(BigDecimal.ZERO) { s,o -> s+o.getString("cost").toBigDecimal()-o.getString("basis").toBigDecimal()-o.getString("booked_fee").toBigDecimal() }+ordersFor(a,l).filter { it.getString("side")=="buy" }.fold(BigDecimal.ZERO) { s,o -> s-o.getString("booked_fee").toBigDecimal() } }.min(BigDecimal.ZERO)
   val pool=amount(policy.getString("value")); val mode=policy.getString("mode")
   if(mode=="units") require(host.sumOf { units(a,it)+pending(a,it,"buy") }+quantity<=pool.toInt()) { "Host unit pool exceeded" }
   else { val capacity=if(mode=="equity_percent") (amount(equity)*pool/BigDecimal(100)).setScale(2,RoundingMode.DOWN) else pool; require(used+charge<=capacity+losses) { "Host monetary pool exceeded" } }
  }
  if(lot==null) {
   require(!sell); val id=root().getInt("next"); require(id<Int.MAX_VALUE); root().put("next",id+1)
   lot=JSONObject().put("id",id).put("route",route).put("trade",trade).put("symbol",event.getString("symbol")).put("asset",asset).put("multiplier",multiplier).put("active",true).put("invalid",false)
   a.getJSONArray("lots").put(lot)
  }
  a.getJSONArray("orders").put(JSONObject().put("cid",cid).put("bank_id",lot.getInt("id")).put("event",event.getString("event_id")).put("side",if(sell) "sell" else "buy").put("ordinal",ordinal).put("quantity",quantity).put("price",price).put("fee",fee.toPlainString()).put("status","unknown").put("broker","").put("filled",0).put("cost","0").put("basis","0").put("charge",charge.toPlainString()).put("booked_fee","0"))
  a.put("available",(a.getString("available").toBigDecimal()-charge).toPlainString()); save(); cid
 }
 private fun block(a:JSONObject,reason:String):Nothing { a.put("blocked",reason); save(); throw IllegalArgumentException(reason) }
 fun observe(scope:String,cid:String,snapshot:JSONObject)=locked {
  val a=account(scope); val o=rows(a.getJSONArray("orders")).single { it.getString("cid")==cid }; val l=rows(a.getJSONArray("lots")).single { it.getInt("id")==o.getInt("bank_id") }
  val audit=a.optJSONArray("audit") ?: JSONArray().also { a.put("audit",it) }
  if(o.optString("last_snapshot")!=snapshot.toString()) { audit.put(JSONObject().put("at",java.time.Instant.now().toString()).put("cid",cid).put("snapshot",JSONObject(snapshot.toString()))); o.put("last_snapshot",snapshot.toString()) }
  try {
   require(snapshot.getString("id").isNotBlank() && (o.getString("broker").isBlank() || snapshot.getString("id")==o.getString("broker")))
   require(snapshot.getString("client_order_id")==cid && snapshot.getString("symbol")==l.getString("symbol") && snapshot.getString("side")==o.getString("side") && snapshot.getString("qty").toBigDecimal()==o.getInt("quantity").toBigDecimal())
   val filled=snapshot.getString("filled_qty").toBigDecimal().intValueExact(); require(filled in o.getInt("filled")..o.getInt("quantity")); val status=snapshot.getString("status"); require(status in statuses && status!="unknown" && status!="superseded")
   require(status!="filled" || filled==o.getInt("quantity")) { "Filled status requires the full requested quantity" }
   val previous=o.getInt("filled"); val oldCost=o.getString("cost").toBigDecimal(); val cost=if(filled==0) BigDecimal.ZERO else amount(snapshot.getString("filled_avg_price"))*filled.toBigDecimal()*l.getInt("multiplier").toBigDecimal()
   require(filled==0 || cost>BigDecimal.ZERO); require(cost>=oldCost && (filled!=previous || cost==oldCost))
   val terminalBefore=o.getString("status") in terminal
   require(!terminalBefore || status in terminal) { "Terminal order reopened" }
   val deltaUnits=filled-previous; val deltaCost=cost-oldCost; val limitValue=deltaUnits.toBigDecimal()*amount(o.getString("price"))*l.getInt("multiplier").toBigDecimal()
   require(if(o.getString("side")=="buy") deltaCost<=limitValue else deltaCost>=limitValue) { "Execution violates reserved limit" }
   val late=deltaUnits>0 && (terminalBefore || !l.getBoolean("active"))
   val fee=if(filled>0) amount(o.getString("fee")) else BigDecimal.ZERO
   var available=a.getString("available").toBigDecimal()
   if(o.getString("side")=="buy") {
    val charge=cost+fee+if(status in terminal) BigDecimal.ZERO else (o.getInt("quantity")-filled).toBigDecimal()*amount(o.getString("price"))*l.getInt("multiplier").toBigDecimal()+if(filled==0) amount(o.getString("fee")) else BigDecimal.ZERO
    available+=o.getString("charge").toBigDecimal()-charge; o.put("charge",charge.toPlainString())
   } else {
    val delta=filled-previous; val owned=units(a,l); require(delta<=owned)
    val consumed=if(delta==owned) basis(a,l) else if(delta==0) BigDecimal.ZERO else basis(a,l).multiply(delta.toBigDecimal()).divide(owned.toBigDecimal(),24,RoundingMode.DOWN)
    o.put("basis",(o.getString("basis").toBigDecimal()+consumed).toPlainString()); available+=consumed.min((cost-oldCost-fee+o.getString("booked_fee").toBigDecimal()).max(BigDecimal.ZERO))
   }
   a.put("available",available.toPlainString()); o.put("status",status).put("broker",snapshot.getString("id")).put("filled",filled).put("cost",cost.toPlainString()).put("booked_fee",fee.toPlainString())
   require(units(a,l)>=0 && pending(a,l,"sell")<=units(a,l) && basis(a,l)>=BigDecimal.ZERO)
   if(late) { l.put("active",true).put("invalid",true); a.put("blocked","Late terminal fill; preserve original ownership and reconcile") }
   if(available<BigDecimal.ZERO) a.put("blocked","Cash capacity deficit; verified flat reconciliation required")
   retire(a,l); save()
  } catch(error:Exception) { if(a.getString("blocked").isEmpty()) { a.put("blocked","Contradictory broker evidence; retain original account and client IDs"); save() }; throw error }
 }
 fun inventory(scope:String,positions:Map<String,Int>)=locked {
  val a=account(scope); require(positions.values.all { it>=0 }); val expected=mutableMapOf<String,Int>(); val baseline=a.getJSONObject("baseline")
  baseline.keys().forEach { expected[it]=baseline.getInt(it) }; rows(a.getJSONArray("lots")).forEach { l -> val s=l.getString("symbol"); expected[s]=(expected[s] ?: 0)+units(a,l) }
  if((positions.keys+expected.keys).any { (positions[it] ?: 0)!=(expected[it] ?: 0) }) { if(a.getString("blocked").isBlank() || a.getString("blocked")=="Inventory differs from owned lots and external baseline") a.put("blocked","Inventory differs from owned lots and external baseline"); save(); throw IllegalArgumentException(a.getString("blocked")) }
  if(a.getString("blocked")=="Inventory differs from owned lots and external baseline") { a.put("blocked",""); save() }
 }
 fun refreshFlatFunds(scope:String,cash:String,equity:String)=locked {
  val a=account(scope); val flat=rows(a.getJSONArray("lots")).all { units(a,it)==0 } && rows(a.getJSONArray("orders")).all { it.getString("status") in terminal }
  if(flat && a.getString("blocked").isEmpty()) { a.put("available",amount(cash).min(amount(equity)).toPlainString()); save() }
 }
 /** Called only after a stopped, complete broker-backed sweep, never by normal dispatch. */
 fun repairVerifiedFlat(scope:String,cash:String,equity:String)=locked {
  val a=account(scope); require(amount(equity)>BigDecimal.ZERO)
  require(a.getString("blocked") in setOf("","Cash capacity deficit; verified flat reconciliation required","Late terminal fill; preserve original ownership and reconcile","Contradictory broker evidence; retain original account and client IDs"))
  require(rows(a.getJSONArray("lots")).all { units(a,it)==0 } && rows(a.getJSONArray("orders")).all { it.getString("status") in terminal }) { "Repair requires every host lot flat and every original order terminal" }
  val priorBlock=a.getString("blocked"); val audit=a.optJSONArray("audit") ?: JSONArray().also { a.put("audit",it) }
  rows(a.getJSONArray("lots")).forEach { retire(a,it) }
  a.put("available",amount(cash).min(amount(equity)).toPlainString()).put("blocked","")
  audit.put(JSONObject().put("kind","verified_flat_repair").put("at",java.time.Instant.now().toString()).put("prior_block",priorBlock).put("cash",cash).put("equity",equity).put("available",a.getString("available")).put("retained_ids",JSONArray(rows(a.getJSONArray("lots")).map { it.getInt("id") })))
  save()
 }
 fun report(scope:String):JSONObject=locked {
  val a=account(scope); val active=JSONArray(); val archived=JSONArray()
  for(l in rows(a.getJSONArray("lots"))) { val row=JSONObject(l.toString()).put("units",units(a,l)).put("pending_buy",pending(a,l,"buy")).put("pending_exit",pending(a,l,"sell")); if(l.getBoolean("active")) active.put(row) else archived.put(row) }
  JSONObject().put("scope",scope).put("blocked",a.getString("blocked")).put("available",a.getString("available")).put("active",active).put("archived",archived).put("baseline",JSONObject(a.getJSONObject("baseline").toString())).put("orders",JSONArray(a.getJSONArray("orders").toString())).put("policies",JSONObject(a.getJSONObject("policies").toString()))
 }
}


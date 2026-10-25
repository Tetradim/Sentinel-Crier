package com.sentinel.crier

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.time.Instant
import java.util.concurrent.atomic.AtomicLong

/** Alerts capabilities deliberately have no order submission/cancellation interface. */
interface FillReadPort {
 fun account():String
 fun fills(after:String, page:String?):JSONArray
}
class AlpacaFillReader(private val config:JSONObject,
 private val get:(String,Map<String,String>)->Any={ url,headers -> Network.requestValue(url,headers=headers) }):FillReadPort {
 private val base=when(config.getString("environment")) { "paper"->"https://paper-api.alpaca.markets"; "live"->"https://api.alpaca.markets"; else->error("Choose paper or live") }
 private val headers=mapOf("APCA-API-KEY-ID" to config.getString("key"),"APCA-API-SECRET-KEY" to config.getString("secret"))
 override fun account():String { val a=get("$base/v2/account",headers) as JSONObject; require(a.optString("id").isNotBlank()) { "Broker account identity unavailable" }; return a.getString("id") }
 override fun fills(after:String,page:String?):JSONArray {
  fun encode(s:String)=URLEncoder.encode(s,"UTF-8")
  return get("$base/v2/account/activities/FILL?direction=asc&page_size=100&after=${encode(after)}"+(page?.let { "&page_token=${encode(it)}" } ?: ""),headers) as JSONArray
 }
}
interface AlertsDocument { fun read():JSONObject; fun write(value:JSONObject) }
/** Activities share one writer so late acknowledgements cannot overwrite a newer root snapshot. */
class AlertsSessionOwner {
 private var instance:GuidedAlerts?=null
 @Synchronized fun get(create:()->GuidedAlerts):GuidedAlerts=instance ?: create().also { instance=it }
}

/** Durable state is scoped by verified account + environment, never by a mirroring channel. */
class GuidedAlerts(private val document:AlertsDocument,
 private val reader:(JSONObject)->FillReadPort={ AlpacaFillReader(it) },
 private val send:(String,JSONObject)->JSONObject={ url,body -> Network.request(url,"POST",body=body) },
 private val now:()->Instant={ Instant.now() }) {
 private val generation=AtomicLong()
 @Volatile private var verified=false
 @Volatile private var previewed=false
 @Volatile private var enabled=false
 @Volatile var testEvidence="No test sent this session"; private set
 @Volatile var evidence="Saved settings are reusable; verify account, preview and enable explicitly"; private set
 private var root=document.read()
 @Volatile private var configSnapshot=root.optJSONObject("config")?.toString() ?: "{}"
 fun revision():Long=generation.get()
 fun saved():JSONObject=JSONObject(configSnapshot)
 fun invalidate() { synchronized(generation) { generation.incrementAndGet(); verified=false; previewed=false; enabled=false; testEvidence="No current test evidence"; evidence="Setup changed or monitoring stopped; verify again" } }
 private fun finish(ticket:Long,action:()->Unit) { synchronized(generation) { current(ticket); action() } }
 private fun current(ticket:Long) { check(ticket==generation.get()) { "Setup changed; result ignored. Verify again." } }
 private fun scope(c:JSONObject)=c.getString("environment")+":"+c.getString("account")
 private fun state(c:JSONObject=saved()):JSONObject {
  val scopes=root.optJSONObject("scopes") ?: JSONObject().also { root.put("scopes",it) }
  return scopes.optJSONObject(scope(c)) ?: JSONObject().put("jobs",JSONArray()).put("seen",JSONObject()).also { scopes.put(scope(c),it) }
 }
 private fun persist()=document.write(root)
 fun verify(input:JSONObject) {
  invalidate(); val ticket=generation.get(); val c=JSONObject(input.toString()); require(c.optString("key").isNotBlank() && c.optString("secret").isNotBlank()) { "Enter your Alpaca credentials" }
  require(c.getString("environment") in setOf("paper","live"))
  c.put("discordWebhook",c.optString("discordWebhook").takeIf { it.isNotBlank() }?.let { Discord.destination(it) } ?: "")
  Discord.preview(c)
  val account=reader(c).account(); current(ticket); c.put("account",account)
  val target=state(c)
  if(target.has("destination") && target.getString("destination")!=c.optString("discordWebhook")) {
   require(!hasUnresolved(target)) { "Inspect and close undelivered alerts before changing destination; history is retained" }
  }
  target.put("destination",c.optString("discordWebhook"))
  root.put("config",c); persist(); configSnapshot=c.toString()
  finish(ticket) { verified=true; evidence="Verified read access · ${c.getString("environment")} account ${account.take(8)}. Preview next." }
 }
 fun preview():String { val ticket=generation.get(); check(verified) { "Verify account first" }; val result=Discord.readablePreview(saved()); finish(ticket) { previewed=true }; return result }
 private fun ready():JSONObject { check(verified && previewed) { "Verify account and preview this setup first" }; return saved().also { require(it.optString("discordWebhook").isNotBlank()) { "Enter a Discord webhook and verify setup" } } }
 fun test():String {
  val ticket=generation.get(); val c=ready(); val store=store(c)
  val id=Discord.test(store); current(ticket); Discord.deliver(store,c,id) { url,body -> current(ticket); send(url,body) }; current(ticket)
  val job=jobs(state(c)).first { it.getString("id")==id }
  finish(ticket) { testEvidence="Synthetic test: ${job.getString("state")} · ${job.optString("detail")}" }
  return testEvidence
 }
 fun enable() { val ticket=generation.get(); val c=ready(); val s=state(c); if(!s.has("after")) { s.put("after",now().toString()); persist() }; finish(ticket) { enabled=true; evidence="Enabled in foreground - new fills after ${s.getString("after")}. Test delivery is optional and separate." } }
 fun isEnabled()=enabled
 fun stop()=invalidate()
 fun tick() {
  check(enabled) { "Enable alerts explicitly" }; val ticket=generation.get(); val c=ready(); val s=state(c); val broker=reader(c)
  try {
   require(broker.account()==c.getString("account")) { "Account identity changed; verify again" }; current(ticket)
   // Cursor moves only after each complete page is validated and durably enqueued.
   val page=broker.fills(s.getString("after"),s.optString("page").ifBlank { null }); current(ticket)
   val records=(0 until page.length()).map { fillRecord(page.getJSONObject(it),Instant.parse(s.getString("after"))) }
   val seen=s.getJSONObject("seen")
   for((id,record) in records) if(!seen.has(id)) { store(c).enqueueAlert("fill:$id",record); seen.put(id,true) }
   if(page.length()>0) { val last=page.getJSONObject(page.length()-1).getString("id"); require(last!=s.optString("page")) { "Broker pagination stalled; monitoring stopped" }; s.put("page",last) }
   persist(); current(ticket)
   Discord.deliver(store(c),c,send={ url,body -> current(ticket); send(url,body) }); current(ticket)
   finish(ticket) { evidence="Read-only fills checked ${now()} · ${summary()}" }
  } catch(e:Exception) { enabled=false; verified=false; previewed=false; evidence="Monitoring stopped; verify and enable again. ${if(e is HttpError) "HTTP ${e.status}" else "Broker or delivery check failed"}"; throw e }
 }
 private fun fillRecord(f:JSONObject,baseline:Instant):Pair<String,JSONObject> {
  val id=f.getString("id"); require(id.isNotBlank() && f.optString("activity_type")=="FILL")
  val time=Instant.parse(f.getString("transaction_time")); require(!time.isBefore(baseline)) { "Fill predates initial monitoring baseline" }
  val qty=f.getString("qty").toBigDecimal(); val price=f.getString("price").toBigDecimal()
  require(qty.signum()>0 && price.signum()>0 && f.getString("side") in setOf("buy","sell") && f.getString("symbol").isNotBlank() && f.getString("order_id").isNotBlank())
  return id to JSONObject().put("source","broker_fill").put("at",time.toString()).put("symbol",f.getString("symbol")).put("action",f.getString("side")).put("quantity",qty.toPlainString()).put("price",price.toPlainString()).put("status","Alpaca FILL activity · incremental execution").put("trade_id",f.getString("order_id"))
 }
 private fun jobs(s:JSONObject):List<JSONObject> { val a=s.getJSONArray("jobs"); return (0 until a.length()).map { a.getJSONObject(it) } }
 private fun hasUnresolved(s:JSONObject)=jobs(s).any { it.getString("state") !in setOf("delivered","discarded") }
 fun summary():String { val c=saved(); if(!c.has("account")) return "No verified saved account"; return jobs(state(c)).groupingBy { it.getString("state") }.eachCount().toString().ifBlank { "No messages" } }
 fun history():String { val c=saved(); if(!c.has("account")) return "No alerts history"; return jobs(state(c)).joinToString("\n") { "${it.getString("id")} · ${it.getString("state")} · ${it.optString("detail")}" }.ifBlank { "No messages" } }
 fun closeInspected() { check(!enabled) { "Stop monitoring first" }; val c=saved(); require(c.has("account")); jobs(state(c)).filter { it.getString("state") !in setOf("delivered","discarded") }.forEach { it.put("state","discarded").put("detail","User closed after inspection; history retained") }; persist() }
 private fun store(c:JSONObject):AlertStore=object:AlertStore {
  private val s=state(c)
  override fun meta(key:String)=s.optString(key)
  override fun setMeta(key:String,value:String) { s.put(key,value); persist() }
  override fun enqueueAlert(id:String,payload:JSONObject) { if(jobs(s).none { it.getString("id")==id }) { s.getJSONArray("jobs").put(JSONObject().put("id",id).put("payload",payload).put("state","pending").put("attempts",0)); persist() } }
  override fun claimAlert(now:Long,id:String?):JSONObject? { val job=jobs(s).firstOrNull { it.getString("state")=="pending" && it.optLong("retryAt")<=now && (id==null || it.getString("id")==id) } ?: return null; job.put("state","uncertain").put("detail","Dispatch started; acknowledgement unavailable").put("attempts",job.getInt("attempts")+1); persist(); return job }
  override fun alertResult(id:String,state:String,delay:Long,detail:String) { val job=jobs(s).first { it.getString("id")==id }; job.put("state",state).put("detail",detail).put("retryAt",System.currentTimeMillis()+delay); persist() }
 }
}

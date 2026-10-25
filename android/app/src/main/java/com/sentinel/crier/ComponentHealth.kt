package com.sentinel.crier

import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID

typealias HealthObserver=(String,String,String)->Unit
fun reportHealth(observer:HealthObserver?,component:String,state:String,reason:String) { runCatching { observer?.invoke(component,state,reason) } }

/** Informational evidence only: never grants execution or publishing permission. */
class ComponentHealth(private val read:()->JSONObject={JSONObject()},private val write:(JSONObject)->Unit={},
 private val wall:()->Long={System.currentTimeMillis()},private val mono:()->Long={System.nanoTime()/1000000}) {
 data class Ticket(val scope:String,val generation:String)
 data class Row(val component:String,val label:String,val state:String,val lastSuccess:Long?,val ageMillis:Long?,val reason:String?,val recovery:String)
 private data class Session(val ticket:Ticket,var active:Set<String>,val wall:Long,val mono:Long)
 private data class Sample(val state:String,val reason:String,val mono:Long,val success:Long?)
 companion object {
  val labels=linkedMapOf("broker" to "Broker account","fills" to "Fill monitoring","relay_send" to "Trade sharing","relay_receive" to "Trade receiving","execution" to "Execution worker","discord" to "Discord delivery")
  private val ttl=mapOf("broker" to 60000L,"fills" to 45000L,"relay_send" to 60000L,"relay_receive" to 60000L,"execution" to 15000L,"discord" to 60000L)
  private val reasons=setOf("verified","checked","delivered","no_work","connection_failed","authentication_failed","rejected","uncertain","rate_limited","invalid_events","reconciliation_required","customer_required","waiting_retry")
  fun scope(config:JSONObject,journey:String):String {
   val fields=listOf("environment","account","url","token","role","discordWebhook","oauthOwner","oauthService","discordOAuthOwner","discordOAuthService")
   val identity=org.json.JSONArray().put(journey); fields.forEach { identity.put(config.optString(it)) }
   return MessageDigest.getInstance("SHA-256").digest(identity.toString().toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
  }
  fun describe(rows:List<Row>,unavailable:Boolean):String {
   val intro="Selected journey only; other workers have separate records. Observed checks do not resume monitoring. Idle means no queued work, not proven connectivity. Android can suspend background workers.\n\n"
   val warning=if(unavailable) "Health history unavailable; current observations may be incomplete. Trading journals remain retained.\n\n" else ""
   return warning+intro+rows.joinToString("\n\n") { r ->
    val at=r.lastSuccess?.let { runCatching { java.time.Instant.ofEpochMilli(it).toString() }.getOrDefault("Timestamp unavailable") } ?: "Never confirmed"
    "${r.label}: ${r.state.replace('_',' ')}\nLast success (UTC): $at\nLast result: ${r.reason?.replace('_',' ') ?: "Not checked"}\n${r.recovery}"
   }
  }
 }
 @Volatile private var problem=false
 @Volatile private var persistenceProblem=false
 val unavailable:Boolean get()=problem || persistenceProblem
 fun persistenceResult(okay:Boolean) { persistenceProblem=!okay }
 private var readable=true
 private val root=try { read().also { if(it.length()>0) require(it.optInt("version")==1 && it.optJSONObject("rows")!=null) } } catch(_:Exception) { problem=true; readable=false; JSONObject() }
 private val sessions=mutableMapOf<String,Session>()
 private val samples=mutableMapOf<Pair<String,String>,Sample>()
 private var latest=root.optString("latest")
 private fun rows():JSONObject=root.optJSONObject("rows") ?: JSONObject().also { root.put("version",1).put("rows",it) }
 private fun persist() { if(!readable) return; try { write(JSONObject(root.toString())); problem=false } catch(_:Exception) { problem=true } }
 @Synchronized fun begin(scope:String,active:Set<String>,journey:String="connection"):Ticket {
  require(active.all { it in labels } && journey in setOf("connection","alerts","intent")); samples.keys.filter { it.first==scope }.forEach { samples.remove(it) }
  val t=Ticket(scope,UUID.randomUUID().toString()); sessions[scope]=Session(t,active.toSet(),wall(),mono())
  latest=scope; root.put("latest",scope); val contexts=root.optJSONObject("contexts") ?: JSONObject().also { root.put("contexts",it) }; contexts.put(journey,scope); rows(); persist(); return t
 }
 @Synchronized fun context(journey:String):String=root.optJSONObject("contexts")?.optString(journey)?.ifBlank { null } ?: latest
 @Synchronized fun setActive(ticket:Ticket,active:Set<String>) { require(active.all { it in labels }); sessions[ticket.scope]?.takeIf { it.ticket==ticket }?.active=active.toSet() }
 fun observer(ticket:Ticket):HealthObserver={ component,state,reason -> record(ticket,component,state,reason) }
 @Synchronized fun stop(ticket:Ticket) { if(sessions[ticket.scope]?.ticket==ticket) sessions.remove(ticket.scope) }
 @Synchronized fun record(ticket:Ticket,component:String,state:String,reason:String) {
  require(component in labels && state in setOf("healthy","degraded","blocked","idle") && reason in reasons)
  if(sessions[ticket.scope]?.ticket!=ticket) return
  val key=ticket.scope to component; val before=samples[key]; val m=mono()
  if(before!=null && before.state==state && before.reason==reason && (state!="healthy" || m-before.mono<2000)) return
  val scope=rows().optJSONObject(ticket.scope) ?: JSONObject().also { rows().put(ticket.scope,it) }
  val old=scope.optJSONObject(component)
  val r=JSONObject().put("generation",ticket.generation).put("state",state).put("reason",reason)
  val success=if(state=="healthy") wall() else old?.opt("success")
  if(success!=null && success!=JSONObject.NULL) r.put("success",success)
  scope.put(component,r); samples[key]=Sample(state,reason,m,if(state=="healthy") m else before?.success); persist()
 }
 @Synchronized fun snapshot(scope:String=latest):List<Row> {
  val session=sessions[scope]; val saved=rows().optJSONObject(scope); val m=mono()
  val drift=session?.let { kotlin.math.abs((wall()-it.wall)-(m-it.mono))>5000 } ?: false
  return labels.map { (id,label) ->
   val r=saved?.optJSONObject(id); val age=samples[scope to id]?.success?.let { maxOf(0,m-it) }
   var state=if(session==null || id !in session.active) "stopped" else if(r?.optString("generation")==session.ticket.generation) r.optString("state") else "waiting"
   if(state=="healthy") state=if(drift) "clock_changed" else if(age==null || age>=ttl.getValue(id)) "stale" else state
   val hint=when { state=="clock_changed"->"Check the device clock, then reconnect."; id=="discord"->"Inspect delivery history before retrying uncertain messages."; id=="execution"->"Inspect broker orders and reconnect for reconciliation."; id.startsWith("relay")->"Inspect the saved connection; reconnect explicitly."; else->"Reconnect the same account; saved journals remain." }
   Row(id,label,state,r?.takeIf { it.has("success") }?.optLong("success"),age,r?.optString("reason")?.ifBlank { null },hint)
  }
 }
}

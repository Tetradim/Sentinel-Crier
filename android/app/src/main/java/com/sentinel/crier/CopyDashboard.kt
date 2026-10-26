package com.sentinel.crier

import org.json.JSONObject
import java.time.Instant

object CopyDashboardCache {
 private var scope=""
 private var snapshot:JSONObject?=null
 private fun key(config:JSONObject)=listOf("url","token","role","environment","account").joinToString("|") { config.optString(it) }
 @Synchronized fun accept(config:JSONObject,value:JSONObject) {
  require(value.getInt("version")==1 && value.getString("environment")==config.getString("environment") && value.getString("role")==config.getString("role"))
  require(value.getJSONArray("events").length()<=50 && value.getJSONArray("statuses").length()<=200 && value.getJSONArray("members").length()<=200 && value.getJSONArray("diagnostics").length()<=200)
  Instant.parse(value.getString("generated_at")); scope=key(config); snapshot=JSONObject(value.toString())
 }
 @Synchronized fun read(config:JSONObject):JSONObject?=if(scope==key(config)) snapshot?.let { JSONObject(it.toString()) } else null
 @Synchronized fun clear() { scope=""; snapshot=null }
 fun describe(value:JSONObject):String=buildString {
  append("${value.getString("role")} · ${value.getString("environment")}\nAs of ${value.getString("generated_at")} · device-reported broker evidence\n")
  if(value.optBoolean("truncated")) append("Partial snapshot: some rows omitted. No complete portfolio total.\n")
  val members=value.getJSONArray("members")
  for(i in 0 until members.length()) { val m=members.getJSONObject(i); val p=m.optJSONObject("presence"); val seen=m.optString("last_seen_at"); val age=runCatching { java.time.Duration.between(Instant.parse(seen),Instant.now()).seconds }.getOrNull(); append("\n${m.getString("actor")} · ${m.getString("role")} · ${p?.optString("platform") ?: "unknown platform"} · ${p?.optString("transport") ?: "unknown transport"} · ${if(m.optBoolean("revoked")) "revoked" else if(age==null || age>45) "stale/offline" else "seen ${age}s ago"}\n") }
  val events=value.getJSONArray("events"); val statuses=value.getJSONArray("statuses")
  for(i in 0 until events.length()) {
   val e=events.getJSONObject(i); append("\n${e.getString("symbol")} · host ${e.getString("action")} ${e.getInt("quantity")} @ ${e.getString("limit_price")}\n")
   var found=false
   for(j in 0 until statuses.length()) {
    val row=statuses.getJSONObject(j); val r=row.getJSONObject("report"); if(r.optString("event_id")!=e.getString("event_id")) continue
    found=true; append("${row.getString("actor")} · ${r.getString("state")} · ${r.optString("reason").takeUnless { it=="null" } ?: "no reported reason"}\nLocal target ${r.opt("target_quantity")} · bought ${r.getInt("bought")} / sold ${r.getInt("sold")} / remaining ${r.getInt("bought")-r.getInt("sold")}\nEntry ${CopyReports.average(r,"buy")} · exit ${CopyReports.average(r,"sell")}\n${CopyReports.money(r)}\nReceived ${row.optString("received_at")} · broker as of ${r.optString("broker_observed_at")}\n")
   }
   if(!found) append("Status unavailable for this source revision.\n")
   val source=(0 until statuses.length()).map { statuses.getJSONObject(it) }.firstOrNull { it.optString("actor")=="host" && it.getJSONObject("report").optString("event_id")==e.getString("event_id") }?.getJSONObject("report")
   for(j in 0 until statuses.length()) {
    val row=statuses.getJSONObject(j); val r=row.getJSONObject("report")
    if(row.optString("actor")=="host" || r.optString("event_id")!=e.getString("event_id")) continue
    if(source!=null) for(side in listOf("buy","sell")) {
     val local=CopyReports.average(r,side).substringBefore(" (rounded)").toBigDecimalOrNull(); val host=CopyReports.average(source,side).substringBefore(" (rounded)").toBigDecimalOrNull()
     append("${row.optString("actor")} − host actual $side premium: ${if(local!=null && host!=null) local.subtract(host).stripTrailingZeros().toPlainString() else "unavailable"} (rounded)\n")
    }
    append("Open estimate USD ${CopyReports.metrics(r).opt("unrealized_estimate").takeUnless { it==JSONObject.NULL } ?: "unavailable"}\n")
    val observations=org.json.JSONArray(); val diagnostics=value.getJSONArray("diagnostics")
    for(k in 0 until diagnostics.length()) { val d=diagnostics.getJSONObject(k); if(d.optString("event_id")==e.getString("event_id") && d.optString("actor") in setOf("host",row.getString("actor"))) observations.put(d) }
    append(Diagnostics.describe(JSONObject().put("event",e).put("timeline",org.json.JSONArray()).put("relay",JSONObject().put("observations",observations)))+"\n")
   }
  }
  append("\nMissing or stale telemetry never means positions closed. Source and receiver fills may differ. Quotes and clock estimates unavailable without fresh verified evidence.")
 }
}

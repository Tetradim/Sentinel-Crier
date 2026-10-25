package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONArray
import java.time.Instant
import android.os.SystemClock
class Diagnostics(private val journal:Journal,private val config:JSONObject) {
 private val url=config.getString("url").trimEnd('/')
 private val auth=mapOf("Authorization" to "Bearer ${config.getString("token")}")
 private var clock:DiagnosticClock.Sample?=null
 private var clockMono=0L
 private val samples=mutableListOf<DiagnosticClock.Sample>()
 fun tick() {
  clock?.let { if(kotlin.math.abs((System.currentTimeMillis()-it.sampledAt)-(SystemClock.elapsedRealtime()-clockMono))>100) { clock=null; samples.clear() } }
  if(clock==null || System.currentTimeMillis()-clock!!.sampledAt>30000) try {
   val before=System.currentTimeMillis(); val mono=SystemClock.elapsedRealtime()
   val r=Network.request("$url/api/sync/clock",headers=auth)
   clock=DiagnosticClock.probe(before,System.currentTimeMillis(),SystemClock.elapsedRealtime()-mono,r.getLong("server_time_ms"))
   clockMono=SystemClock.elapsedRealtime(); clock?.let { samples.add(it) }; samples.removeAll { System.currentTimeMillis()-it.sampledAt>60000 }
  } catch(_:Exception) { clock=null }
  for(e in journal.diagnosticEvents()) {
   val id=e.getString("event_id"); val lines=journal.timeline(id)
   val local=(0 until lines.length()).map { lines.getJSONObject(it) }.firstOrNull { it.getString("stage") in setOf("sender","receiver") } ?: continue
   var raw=journal.meta("observation:$id")
   if(raw.isBlank()) {
    val at=local.getString("at"); val stamp=Instant.parse(at).toEpochMilli()
    val sample=samples.lastOrNull { stamp-it.sampledAt in 0..60000 && it.uncertainty<=30000 }
    val o=JSONObject().put("stage",local.getString("stage")).put("observed_at",at).put("clock_offset_ms",sample?.offset ?: JSONObject.NULL).put("clock_uncertainty_ms",sample?.uncertainty ?: JSONObject.NULL).put("clock_sampled_at",sample?.let { Instant.ofEpochMilli(it.sampledAt).toString() } ?: JSONObject.NULL).put("quote",JSONObject.NULL).put("quote_error",JSONObject.NULL)
    try { o.put("quote",quote(e)) } catch(error:Exception) { o.put("quote_error",if(error is HttpError) "Alpaca quote unavailable (HTTP ${error.status})" else "Alpaca quote unavailable") }
    raw=o.toString(); journal.setMeta("observation:$id",raw)
   }
   val nextAttempt=journal.meta("diagnosticNext:$id").toLongOrNull() ?: 0L
   if(System.currentTimeMillis()<nextAttempt) continue
   journal.setMeta("diagnosticNext:$id",(System.currentTimeMillis()+5000).toString())
   val attempts=journal.meta("diagnosticAttempts:$id").toIntOrNull() ?: 0
   val ready=local.getString("stage")=="receiver" || (0 until lines.length()).any { lines.getJSONObject(it).getString("stage")=="relay_ack" }
   if(ready && journal.meta("diagnosticSent:$id")!="yes" && attempts<5) {
    journal.setMeta("diagnosticAttempts:$id",(attempts+1).toString())
    try { Network.request("$url/api/sync/diagnostics","POST",auth,JSONObject().put("event_id",id).put("observation",JSONObject(raw))); journal.setMeta("diagnosticSent:$id","yes") } catch(_:Exception) { }
   }
   val fetches=journal.meta("diagnosticFetches:$id").toIntOrNull() ?: 0
   if(ready && fetches<20) { journal.setMeta("diagnosticFetches:$id",(fetches+1).toString()); try { journal.setMeta("remoteEvidence:$id",Network.request("$url/api/sync/diagnostics?event_id=$id",headers=auth).toString()) } catch(_:Exception) { } }
  }
 }
 private fun quote(e:JSONObject):JSONObject {
  val symbol=e.getString("symbol"); val option=e.getString("asset")=="option"
  val endpoint=if(option) "https://data.alpaca.markets/v1beta1/options/quotes/latest?symbols=$symbol&feed=opra" else "https://data.alpaca.markets/v2/stocks/$symbol/quotes/latest?feed=iex"
  val r=Network.request(endpoint,headers=BrokerAuth.headers(config))
  val q=if(option) r.getJSONObject("quotes").getJSONObject(symbol) else r.getJSONObject("quote"); val quoteAt=Instant.parse(q.getString("t")); val sample=clock ?: error("Clock unavailable"); require(System.currentTimeMillis()-sample.sampledAt in 0..60000 && kotlin.math.abs((System.currentTimeMillis()-sample.sampledAt)-(SystemClock.elapsedRealtime()-clockMono))<=100); val now=Instant.ofEpochMilli((System.currentTimeMillis()+sample.offset).toLong()); require(quoteAt<=now && java.time.Duration.between(quoteAt,now).toMillis()<=5000)
  fun price(k:String):Any = if(!q.has(k) || q.isNull(k)) JSONObject.NULL else boundedPrice(q.get(k).toString()) ?: JSONObject.NULL
  return JSONObject().put("source",if(option) "alpaca:opra" else "alpaca:iex").put("quote_timestamp",q.getString("t")).put("bid",price("bp")).put("ask",price("ap")).put("last",JSONObject.NULL)
 }
 companion object {
  fun boundedPrice(raw:String):String? = try { require(raw.length<=40); val n=raw.toBigDecimal(); require(n.signum()>0 && n<=java.math.BigDecimal("1000000000000") && n.scale() in -12..12); n.toPlainString() } catch(_:Exception) { null }
  fun export(j:Journal):JSONArray = JSONArray().also { a -> j.diagnosticEvents().forEach { e -> val id=e.getString("event_id"); a.put(JSONObject().put("event",e).put("timeline",j.timeline(id)).put("local",j.meta("observation:$id").takeIf { it.isNotBlank() }?.let { JSONObject(it) } ?: JSONObject.NULL).put("relay",j.meta("remoteEvidence:$id").takeIf { it.isNotBlank() }?.let { JSONObject(it) } ?: JSONObject.NULL)) } }
  private fun millis(o:JSONObject,key:String)=Instant.parse(o.getString(key)).toEpochMilli()
  fun describe(r:JSONObject):String {
   val e=r.getJSONObject("event"); val local=r.optJSONObject("local"); val rows=r.optJSONObject("relay")?.optJSONArray("observations") ?: JSONArray()
   val entries=(0 until rows.length()).map { rows.getJSONObject(it) }
   val sender=entries.firstOrNull { it.getJSONObject("observation").optString("stage")=="sender" }?.getJSONObject("observation")
   val estimates=entries.filter { it.getJSONObject("observation").optString("stage")=="receiver" }.map { row ->
    val receiver=row.getJSONObject("observation")
    val latency=try { require(sender!=null); DiagnosticClock.latency(millis(sender,"observed_at"),millis(receiver,"observed_at"),sender.getDouble("clock_offset_ms"),receiver.getDouble("clock_offset_ms"),sender.getDouble("clock_uncertainty_ms"),receiver.getDouble("clock_uncertainty_ms"),millis(sender,"clock_sampled_at"),millis(receiver,"clock_sampled_at")) } catch(_:Exception) { null }
    val premium=try {
     require(sender!=null && latency!=null && sender.isNull("quote_error") && receiver.isNull("quote_error") && e.getString("action")!="cancel"); val sq=sender.getJSONObject("quote"); val rq=receiver.getJSONObject("quote"); require(sq.getString("source")== (if(e.optString("asset")=="option") "alpaca:opra" else "alpaca:iex") && sq.getString("source")==rq.getString("source"))
     for((o,q) in listOf(sender to sq,receiver to rq)) require(kotlin.math.abs(millis(o,"observed_at")+o.getDouble("clock_offset_ms")-millis(q,"quote_timestamp"))<=5000)
     val side=if(e.getString("action")=="exit") "bid" else "ask"; val a=boundedPrice(sq.getString(side))!!.toBigDecimal(); val b=boundedPrice(rq.getString(side))!!.toBigDecimal(); require(a.signum()>0 && b.signum()>0)
     "$side sender $a / receiver $b; difference ${b-a} per share (near-event quote, not fill)"
    } catch(_:Exception) { "Premium comparison unavailable: missing, stale or incompatible quotes" }
    "${row.optString("actor")}: "+(latency?.let { "%.1f +/- %.1f ms".format(it.first,it.second) } ?: "Latency unavailable: missing/stale clock evidence")+"\n"+premium
   }
   val side=if(e.getString("action")=="exit") "bid" else "ask"; val q=local?.optJSONObject("quote"); val lines=r.getJSONArray("timeline")
   return "${e.getString("symbol")} ${e.getString("action")} ${e.getString("event_id")}\n"+(q?.let { "$side ${it.optString(side)} - ${it.optString("source")} - ${it.optString("quote_timestamp")}" } ?: local?.optString("quote_error","Quote pending") ?: "Quote pending")+"\n"+estimates.joinToString("\n").ifBlank { "Cross-device latency unavailable; awaiting paired evidence" }+"\n"+(0 until lines.length()).joinToString("\n") { val l=lines.getJSONObject(it); "${l.getString("at")} ${l.getString("stage")} ${l.optString("detail")}" }
  }
  fun csv(records:JSONArray):String {
   fun cell(v:String):String { val clean=v.filter { it>=' ' || it=='\n' || it=='\r' }; val safe=if(v.firstOrNull()?.let { it<' ' || it in "=+-@" }==true || clean.trimStart().firstOrNull()?.let { it in "=+-@" }==true) "'"+clean else clean; return "\""+safe.replace("\"","\"\"")+"\"" }
   return "event_id,symbol,action,diagnostics,evidence_json\r\n"+(0 until records.length()).joinToString("\r\n") { val r=records.getJSONObject(it); val e=r.getJSONObject("event"); listOf(e.getString("event_id"),e.getString("symbol"),e.getString("action"),describe(r),r.toString()).joinToString(",") { cell(it) } }
  }
 }
}

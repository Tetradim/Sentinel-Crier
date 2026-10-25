package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONArray
import java.net.URI
import java.time.Instant
import java.util.UUID

object Discord {
 val fields=listOf("symbol","action","quantity","price","status","trade_id")
 fun destination(text:String):String {
  val u=URI(text.trim())
  require(u.scheme=="https" && u.host in setOf("discord.com","discordapp.com") && u.userInfo==null && u.port==-1 && u.query==null && u.fragment==null && u.path.matches(Regex("/api/webhooks/[0-9]+/[A-Za-z0-9_-]+"))) { "Enter a Discord HTTPS webhook URL." }
  return u.toString()
 }
 fun label(source:String)=when(source) { "intent"->"TRADE INTENT · not a fill"; "manual"->"MANUAL OBSERVATION · unverified"; "broker_fill"->"BROKER FILL · Alpaca reconciliation"; "test"->"TEST MESSAGE · no trade"; else->error("Unknown alert provenance") }
 fun record(source:String,event:JSONObject):JSONObject = JSONObject().put("source",source).put("at",Instant.now().toString()).put("symbol",event.optString("symbol")).put("action",event.optString("action")).put("quantity",event.opt("quantity") ?: "Unavailable").put("price",event.optString("limit_price","Unavailable")).put("status",if(source=="intent") "requested" else "observed").put("trade_id",event.optString("trade_id"))
 fun sample()=record("test",JSONObject().put("symbol","SPY261218C00750000").put("action","buy_to_open").put("quantity",2).put("limit_price","0.20"))
 /** Called only with broker identity and cumulative-fill validated evidence. Never use the intent limit as a fill. */
 fun brokerFill(event:JSONObject,order:JSONObject,side:String):JSONObject {
  val filled=order.getString("filled_qty").toBigDecimal(); require(filled.signum()>0)
  return record("broker_fill",event).put("action",side).put("quantity",filled.stripTrailingZeros().toPlainString()).put("status",order.getString("status")+" (cumulative fill)").put("price",order.optString("filled_avg_price").takeIf { it.toBigDecimalOrNull()?.signum()==1 } ?: "Unavailable")
 }
 fun payload(record:JSONObject,config:JSONObject):JSONObject {
  val provenance=label(record.getString("source"))
  val template=config.optString("discordTemplate","{action} {symbol}")
  require(template.length<=500) { "Template must be at most 500 characters" }
  val matches=Regex("\\{([^{}]+)\\}").findAll(template).toList()
  require(matches.all { it.groupValues[1] in fields }) { "Use only supported template fields: ${fields.joinToString()}" }
  var heading=template
  for(k in fields) heading=heading.replace("{$k}",record.optString(k,"Unavailable"))
  val selected=config.optString("discordFields",fields.joinToString(",")).split(',').filter { it in fields }.distinct()
  val details=selected.joinToString("\n") { "$it: ${record.optString(it,"Unavailable")}" }
  val out=JSONObject().put("allowed_mentions",JSONObject().put("parse",JSONArray()))
  if(config.optString("discordStyle","card")=="plain") out.put("content",("$provenance\n$heading\n$details").take(2000))
  else out.put("embeds",JSONArray().put(JSONObject().put("title",provenance).put("description",heading.take(1000)).put("fields",JSONArray().also { a -> selected.forEach { a.put(JSONObject().put("name",it).put("value",record.optString(it,"Unavailable").ifBlank { "Unavailable" }.take(1024)).put("inline",true)) } }).put("footer",JSONObject().put("text","Crier · ${record.optString("at")}"))))
  return out
 }
 fun preview(config:JSONObject)=payload(sample(),config).toString(2)
 fun readablePreview(config:JSONObject):String {
  val p=payload(sample(),config)
  if(p.has("content")) return p.getString("content")
  val e=p.getJSONArray("embeds").getJSONObject(0); val f=e.getJSONArray("fields")
  return e.getString("title")+"\n\n"+e.getString("description")+"\n\n"+(0 until f.length()).joinToString("\n") { val item=f.getJSONObject(it); "${item.getString("name")}: ${item.getString("value")}" }
 }
 fun test(journal:AlertStore):String { val id="test:${UUID.randomUUID()}"; journal.enqueueAlert(id,sample()); return id }
 fun deliver(journal:AlertStore,config:JSONObject,jobId:String?=null,observe:HealthObserver?=null,send:(String,JSONObject)->JSONObject={ url,body -> Network.request(url,"POST",body=body) }) {
  val webhook=config.optString("discordWebhook"); if(webhook.isBlank()) return
  if(journal.meta("discordRetryAt").toLongOrNull()?.let { it>System.currentTimeMillis() }==true) { reportHealth(observe,"discord","degraded","rate_limited"); return }
  val next=journal.claimAlert(System.currentTimeMillis(),jobId) ?: run {
   if(observe!=null) runCatching { journal.healthStates()?.let { states ->
    when { "uncertain" in states->reportHealth(observe,"discord","blocked","uncertain"); "blocked" in states || "review" in states->reportHealth(observe,"discord","blocked","rejected"); states.isNotEmpty()->reportHealth(observe,"discord","degraded","waiting_retry"); else->reportHealth(observe,"discord","idle","no_work") }
   } }; return
  }
  val id=next.getString("id")
  try {
   // wait=true is required: a message ID is evidence of delivery, a 204 is not.
   val response=send(destination(webhook)+"?wait=true",payload(next.getJSONObject("payload"),config))
   val message=response.optString("id"); require(message.matches(Regex("[0-9]+"))) { "Discord delivery response had no message ID" }
   journal.alertResult(id,"delivered",0,"Discord message $message")
   reportHealth(observe,"discord","healthy","delivered")
  } catch(error:Exception) {
   val permanent=error is HttpError && error.status in setOf(400,401,403,404)
   val delay=if(error is HttpError && error.status==429) maxOf(1000,error.retryAfter*1000) else minOf(300000,1000L*(1L shl minOf(8,next.getInt("attempts"))))
   if(error is HttpError && error.status==429) journal.setMeta("discordRetryAt",(System.currentTimeMillis()+delay).toString())
   val retryable=error is HttpError && error.status==429
   journal.alertResult(id,if(permanent) "blocked" else if(retryable) "pending" else "uncertain",delay,if(error is HttpError) "HTTP ${error.status}; inspect delivery before retrying" else "Delivery acknowledgement unavailable; inspect Discord before explicit retry (duplicates possible)")
   reportHealth(observe,"discord",if(retryable) "degraded" else "blocked",if(retryable) "rate_limited" else if(permanent) "rejected" else "uncertain")
  }
 }
}

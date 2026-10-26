package com.sentinel.crier

import org.json.JSONObject
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant

/** Observational only. Never calls a broker or changes the intent queue. */
object CopyReports {
 private val zero=BigDecimal.ZERO
 fun decimal(raw:String):BigDecimal? = runCatching { require(raw.length<=120 && raw.matches(Regex("(?:0|[1-9][0-9]*)(\\.[0-9]+)?"))); raw.toBigDecimal().also { require(it.stripTrailingZeros().precision()<=80 && it.signum()>=0) } }.getOrNull()
 fun report(store:IntentStore,event:JSONObject):JSONObject {
  val trade=event.getString("trade_id"); val orders=store.orders(trade)
  val bought=orders.filter { it.side=="buy" }.sumOf { it.filled }; val sold=orders.filter { it.side=="sell" }.sumOf { it.filled }
  require(bought in 0..1000000 && sold in 0..bought)
  fun premium(side:String):String? {
   var sum=zero
   for(o in orders.filter { it.side==side && it.filled>0 }) {
    val evidence=runCatching { JSONObject(store.meta("fill:${o.client}")) }.getOrNull() ?: return null
    if(evidence.optInt("filled",-1)!=o.filled) return null
    val price=decimal(evidence.optString("average"))?.takeIf { it.signum()>0 } ?: return null
    sum=sum.add(price.multiply(o.filled.toBigDecimal()))
   }
   return sum.toPlainString().takeIf { decimal(it)!=null }
  }
  val plan=runCatching { JSONObject(store.meta("plan:$trade:${event.getInt("sequence")}")) }.getOrNull()
  val binding=(plan?.optJSONObject("binding") ?: runCatching { JSONObject(store.meta("copyBinding:$trade")) }.getOrNull())?.takeIf { it.optString("environment")==event.getString("environment") && it.optString("currency")=="USD" && it.optString("symbol")==event.getString("symbol") && it.optString("asset")==event.getString("asset") && it.optInt("multiplier")==if(event.getString("asset")=="option") 100 else 1 }
  val skipped=store.meta("timeline:${event.getString("event_id")}:entry_skipped")
  val deferred=store.meta("timeline:${event.getString("event_id")}:entry_deferred")
  val state=when {
   orders.any { it.state in setOf("unknown","cancel_unknown") } -> "unknown"
   bought>0 && bought==sold -> "closed"
   orders.any { it.state=="pending_cancel" || it.state=="cancel_pending" } -> "cancel_pending"
   orders.any { it.state=="partially_filled" } -> "partially_filled"
   orders.any { it.state in setOf("new","accepted","pending_new","working") } -> "working"
   orders.any { it.state=="filled" } -> "filled"
   orders.any { it.state=="canceled" } -> "canceled"
   orders.any { it.state in setOf("rejected","expired") } -> "not_submitted"
   orders.isEmpty() && skipped.isNotBlank() -> "not_submitted"
   orders.isEmpty() && deferred.isNotBlank() -> "blocked"
   else -> "received"
  }
  val observed=orders.map { store.meta("brokerObserved:${it.client}") }.filter { it.isNotBlank() }.maxOrNull()
  return JSONObject().put("version",1).put("event_id",event.getString("event_id")).put("state",state)
   .put("target_quantity",plan?.opt("target") ?: JSONObject.NULL).put("bought",bought).put("sold",sold)
   .put("buy_premium",premium("buy") ?: JSONObject.NULL).put("sell_premium",premium("sell") ?: JSONObject.NULL)
   .put("currency",if(binding!=null) "USD" else JSONObject.NULL).put("multiplier",binding?.getInt("multiplier") ?: JSONObject.NULL)
   .put("broker_observed_at",observed ?: JSONObject.NULL).put("fees",JSONObject.NULL).put("quote",runCatching { JSONObject(store.meta("observation:${event.getString("event_id")}")).optJSONObject("quote") }.getOrNull() ?: JSONObject.NULL)
   .put("reason",if(state=="unknown") "reconciliation_required" else if(state=="blocked") "clock_uncertain" else if(skipped in setOf("entries_paused","expired")) skipped else if(state=="not_submitted") "not_submitted" else JSONObject.NULL)
 }
 fun money(report:JSONObject):String {
  val bought=report.optInt("bought"); val sold=report.optInt("sold")
  val buy=decimal(report.optString("buy_premium")); val sell=decimal(report.optString("sell_premium"))
  if(bought<=0 || bought!=sold || buy==null || sell==null || report.optString("currency")!="USD" || report.optInt("multiplier") !in setOf(1,100)) return "Gross P&L unavailable"
  val gross=sell.subtract(buy).multiply(report.getInt("multiplier").toBigDecimal())
  val fees=decimal(report.optString("fees"))
  return "Gross USD ${gross.setScale(2,RoundingMode.HALF_UP).toPlainString()} · "+(if(fees!=null) "net USD ${gross.subtract(fees).setScale(2,RoundingMode.HALF_UP)}" else "net unavailable (fees unknown)")
 }
 fun average(report:JSONObject,side:String):String {
  val units=report.optInt(if(side=="buy") "bought" else "sold"); val sum=decimal(report.optString("${side}_premium"))
  return if(units>0 && sum!=null) sum.divide(units.toBigDecimal(),8,RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()+" (rounded)" else "unavailable"
 }
 fun metrics(report:JSONObject,now:Instant=Instant.now()):JSONObject {
  val bought=report.getInt("bought"); val sold=report.getInt("sold"); require(bought in 0..1000000 && sold in 0..bought)
  val buy=decimal(report.optString("buy_premium")); val sell=decimal(report.optString("sell_premium")); val fees=decimal(report.optString("fees"))
  val verified=report.optString("currency")=="USD" && report.optInt("multiplier") in setOf(1,100)
  fun usd(v:BigDecimal?)=v?.setScale(2,RoundingMode.HALF_UP)?.toPlainString() ?: JSONObject.NULL
  fun price(v:BigDecimal?,units:Int):Any=if(v!=null && units>0) v.divide(units.toBigDecimal(),8,RoundingMode.HALF_UP).stripTrailingZeros().toPlainString() else JSONObject.NULL
  val gross=if(verified && bought>0 && bought==sold && buy!=null && sell!=null) sell.subtract(buy).multiply(report.getInt("multiplier").toBigDecimal()) else null
  var estimate:BigDecimal?=null
  if(verified && bought>sold && buy!=null) runCatching {
   val quote=report.getJSONObject("quote"); val age=java.time.Duration.between(Instant.parse(quote.getString("quote_timestamp")),now)
   val bid=decimal(quote.optString("bid"))
   if(!age.isNegative && age<=java.time.Duration.ofSeconds(5) && bid!=null) estimate=bid.subtract(buy.divide(bought.toBigDecimal(),120,RoundingMode.HALF_UP)).multiply((bought-sold).toBigDecimal()).multiply(report.getInt("multiplier").toBigDecimal())
  }
  return JSONObject().put("remaining",bought-sold).put("entry_average",price(buy,bought)).put("exit_average",price(sell,sold))
   .put("gross_realized_pnl",usd(gross)).put("net_realized_pnl",usd(if(gross!=null && fees!=null) gross.subtract(fees) else null)).put("unrealized_estimate",usd(estimate))
 }
}
/** Independent, durable, coalescing observational outbox, scoped by the journal's pairing. */
class CopyReporter(private val journal:Journal,private val send:(String,JSONObject)->Unit) {
 fun tick(transport:String,paused:Boolean) {
  for(event in journal.history().take(50)) {
   val id=event.getString("trade_id"); val base=CopyReports.report(journal,event); val signature=base.toString()
   val key="copyStatus:$id"
   if(journal.meta("$key:signature")!=signature) {
    journal.queueCopy(key,signature,base)
   }
   journal.meta("$key:pending").takeIf { it.isNotBlank() }?.let {
    try { send("status",JSONObject(it)); journal.setMeta("$key:pending","") }
    catch(e:HttpError) { if(e.status !in setOf(400,409,422)) throw e; journal.setMeta("$key:pending",""); journal.setMeta("copyTelemetry","Status unavailable: rejected report") }
   }
  }
  val now=System.currentTimeMillis(); val prior=journal.meta("copyPresenceAt").toLongOrNull() ?: 0
  val signature="$transport:$paused"
  if(now-prior>=15000 || journal.meta("copyPresenceState")!=signature) {
   val revision=(journal.meta("copyPresenceRevision").toLongOrNull() ?: 0)+1; require(revision<=9007199254740991L)
   journal.setMeta("copyPresenceRevision",revision.toString())
   send("presence",JSONObject().put("version",1).put("revision",revision).put("observed_at",Instant.now().toString()).put("platform","android").put("transport",transport).put("entries_enabled",!paused))
   journal.setMeta("copyPresenceAt",now.toString()); journal.setMeta("copyPresenceState",signature)
  }
 }
}

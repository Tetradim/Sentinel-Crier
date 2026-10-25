package com.sentinel.crier
import org.json.JSONObject
import java.time.Instant
class Engine(private val journal:IntentStore,private val config:JSONObject,private val broker:BrokerPort=Broker(config),private val clock:()->Instant={ Instant.now() },entryClock:EntryClock?=null,private val paused:()->Boolean) {
 private val entryTime=entryClock ?: EntryClock(clock)
 var reconciliationHealthy=false; private set

 private val terminal=setOf("filled","canceled","expired","rejected","replaced","superseded")
 fun step(e:JSONObject) {
  journal.diagnostic(e.getString("event_id"),"execution_started","Account validation and reconciliation")
  val trade=e.getString("trade_id"); val seq=e.getInt("sequence"); val action=e.getString("action")
  if(!reconcile(e)) return
  val orders=journal.orders(trade)
  val revision=journal.revision(trade)
  val shouldCancel=action in setOf("replace","cancel","exit") || seq<revision.first || revision.second
  if(shouldCancel) {
   for(o in orders.filter { it.side=="buy" && it.state !in terminal && (it.sequence!=seq || action in setOf("cancel","exit") || revision.second) }) {
    val lastAttempt=journal.meta("cancel_attempt_ms:${o.client}").toLongOrNull()
    val now=clock().toEpochMilli()
    if(o.state!="pending_cancel" && (lastAttempt==null || now-lastAttempt>=5000)) {
     journal.setMeta("cancel_attempt_ms:${o.client}",now.toString())
     journal.setMeta("cancel:${o.client}","requested")
     journal.state(o.client,"cancel_unknown")
     journal.diagnostic(e.getString("event_id"),"cancel_requested",o.client)
     broker.cancel(o.broker)
    }
   }
   if(orders.any { it.side=="buy" && it.state !in terminal }) return
  }
  if(seq<revision.first || action=="cancel") { journal.mark(e.getString("event_id"),false); return }
  val sell=action=="exit"
  val filled=orders.filter { it.side=="buy" }.sumOf { it.filled }
  val sold=orders.filter { it.side=="sell" }.sumOf { it.filled }
  val own=orders.lastOrNull { it.sequence==seq }
  if(own!=null && !(sell && own.state=="filled")) {
   if(own.state in terminal) {
    if(sell && own.state!="filled") journal.setMeta("status","Exit stopped: ${own.state}. Inspect broker and create a new exit revision if needed.")
    if(own.state=="rejected" && !sell && config.getString("role")=="host" && !revision.second) journal.create("cancel",e.getString("symbol"),e.getString("asset"),e.getInt("quantity"),e.getString("limit_price"),e.getString("environment"),trade)
    journal.mark(e.getString("event_id"),false)
   }
   return
  }
  if(!sell) {
   val sample=entryTime.read() ?: run { journal.diagnostic(e.getString("event_id"),"entry_deferred","clock_changed"); journal.setMeta("status","New entries deferred: check device time and reconnect. Cancel/exit handling remains active."); return }
   val now=sample.effective; val created=Instant.parse(e.getString("created_at"))
   if(sample.wall<created) { journal.diagnostic(e.getString("event_id"),"entry_deferred","future_created_at"); return }
   val age=java.time.Duration.between(created,now).seconds
   if(!Policy.canEnter(revision.second,paused(),seq,revision.first,age,config.optInt("age",10)) || now>created.plusSeconds(config.optInt("age",10).toLong()) || now>=Instant.parse(e.getString("expires_at")) || e.getInt("quantity")>config.optInt("maxQuantity",1000)) { journal.diagnostic(e.getString("event_id"),"entry_skipped",if(paused()) "entries_paused" else if(now>=Instant.parse(e.getString("expires_at"))) "expired" else if(e.getInt("quantity")>config.optInt("maxQuantity",1000)) "max_quantity" else "age_or_revision_limit"); journal.mark(e.getString("event_id"),false); return }
  }
  if(orders.any { it.state !in terminal }) return
  val remaining=e.getInt("quantity")-orders.filter { it.sequence==seq && it.side=="sell" }.sumOf { it.filled }
  val qty=if(sell) Policy.exitQuantity(remaining,filled,sold,broker.holdings(e.getString("symbol"))) else (e.getInt("quantity")-filled).coerceAtLeast(0)
  if(qty==0 && sell && remaining>0 && filled>sold) return
  if(qty==0) { journal.mark(e.getString("event_id"),false); return }
  val ordinal=orders.count { it.sequence==seq && it.side=="sell" }
  val client="si-${e.getString("event_id")}-${if(sell) "s$ordinal" else "b"}"
  synchronized(journal) {
   val latest=journal.revision(trade)
   if(latest.first!=seq || (!sell && latest.second)) return
   journal.setMeta("quantity:$client",qty.toString())
   journal.unknown(client,trade,seq,if(sell) "sell" else "buy")
  }
  var refused="revision_changed"
  try { val result=broker.submit(e,client,qty,sell) {
   val current=journal.revision(trade)
   if(current.first!=seq) false else if(sell) true else {
    val sample=entryTime.read()
    val created=Instant.parse(e.getString("created_at")); val expiry=Instant.parse(e.getString("expires_at"))
    refused=when { sample==null->"clock_changed"; current.second->"invalidated"; paused()->"entries_paused"; sample.wall<created->"future_created_at"; sample.effective>=expiry->"expired"; sample.effective>created.plusSeconds(config.optInt("age",10).toLong())->"max_age"; e.getInt("quantity")>config.optInt("maxQuantity",1000)->"max_quantity"; else->"" }
    refused.isEmpty()
   }
  }; validate(result,client,e.getString("symbol"),if(sell) "sell" else "buy",qty,0); journal.update(client,result) }
  catch(_:Superseded) { journal.state(client,"superseded"); journal.diagnostic(e.getString("event_id"),"broker_not_submitted",refused); journal.setMeta("status","Not submitted before dispatch: $refused. Journal retained; use a new revision if needed.") }
  catch(error:HttpError) {
   if(error.status in setOf(400,401,403)) {
    journal.state(client,"rejected")
    if(!sell && config.getString("role")=="host") journal.create("cancel",e.getString("symbol"),e.getString("asset"),e.getInt("quantity"),e.getString("limit_price"),e.getString("environment"),trade)
   }
   throw error
  }
 }
 /** Refresh every outstanding order before allowing new work after process/service resume. */
 fun reconcile(e:JSONObject):Boolean {
  reconciliationHealthy=false
  require(broker.account()==config.getString("account")) { "Account changed" }
  for(o in journal.orders(e.getString("trade_id"))) if(o.state !in terminal) {
   val remote=broker.order(o.client)
   if(remote==null) { journal.diagnostic(e.getString("event_id"),"reconciliation_wait","Broker outcome unknown; submission blocked"); return false }
   validate(remote,o.client,e.getString("symbol"),o.side,journal.meta("quantity:${o.client}").toIntOrNull(),o.filled,o.broker)
   journal.update(o.client,remote)
  }
  reconciliationHealthy=true; return true
 }
 private fun validate(order:JSONObject,client:String,symbol:String,side:String,quantity:Int?,previous:Int,expectedBroker:String="") {
  require(order.getString("id").isNotBlank() && (expectedBroker.isBlank() || order.getString("id")==expectedBroker)) { "Broker order ID changed" }
  require(quantity!=null && order.getString("client_order_id")==client && order.getString("symbol")==symbol && order.getString("side")==side && order.getString("qty").toBigDecimal()==quantity.toBigDecimal()) { "Broker order identity mismatch" }
  require(order.getString("status") in setOf("new","accepted","pending_new","accepted_for_bidding","partially_filled","filled","done_for_day","canceled","expired","replaced","pending_cancel","pending_replace","stopped","rejected","suspended","calculated")) { "Invalid broker status" }
  val filled=order.getString("filled_qty").toBigDecimal()
  if(!order.isNull("filled_avg_price") && order.has("filled_avg_price")) require(order.getString("filled_avg_price").toBigDecimal().signum()>0) { "Invalid broker fill price" }
  require(filled>=previous.toBigDecimal() && filled<=quantity.toBigDecimal() && filled.stripTrailingZeros().scale()<=0) { "Invalid cumulative fill" }
 }
}

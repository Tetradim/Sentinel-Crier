package com.sentinel.crier

import org.json.JSONObject

/** Reconciles retained identities before execution can size or dispatch another mutation. */
class OrderReconciler(
 private val journal:IntentStore,
 private val config:JSONObject,
 private val broker:BrokerPort,
 private val monotonic:()->Long
) {
 private val submittedHere=mutableSetOf<String>()
 private var timerSession=java.util.UUID.randomUUID().toString()
 fun reconnect() { timerSession=java.util.UUID.randomUUID().toString() }
 fun submitted(client:String) { submittedHere.add(client) }
 val freshlyReconciled=mutableSetOf<String>()
 var reconciliationError:Exception?=null; private set
 var reconciliationHealthy=false; private set
 private val terminal=setOf("filled","canceled","expired","rejected","replaced","superseded")
 /** Refresh broker-backed evidence, including terminal mutations, at each pending execution boundary. */
 fun reconcile(e:JSONObject):Boolean {
  reconciliationHealthy=false; reconciliationError=null; freshlyReconciled.clear()
  BrokerLifecycleFence.interrupted()
  require(broker.account()==config.getString("account")) { "Account changed" }
  var healthy=true
  for(o in journal.orders(e.getString("trade_id"))) {
   val knownLocalRefusal=o.broker.isBlank() && o.filled==0 && (o.state=="superseded" || (o.state=="rejected" && journal.meta("known_local_refusal:${o.client}") in setOf("http_400","http_401","http_403")))
   if(knownLocalRefusal) continue
   try {
   BrokerLifecycleFence.interrupted()
   if(o.broker.isBlank() && o.filled==0 && broker.locallyRefused(o.client)) {
    journal.state(o.client,"superseded")
    journal.diagnostic(e.getString("event_id"),"broker_not_submitted","Durable account bank refusal recovered")
    continue
   }
   val remote=broker.order(o.client)
   BrokerLifecycleFence.interrupted()
   if(remote==null) { healthy=false; journal.diagnostic(e.getString("event_id"),"reconciliation_wait","Broker outcome unknown; submission blocked"); continue }
   OrderObservation.validate(remote,o.client,e.getString("symbol"),o.side,journal.meta("quantity:${o.client}").toIntOrNull(),o.filled,o.broker)
   val snapshot=journal.policy(e.getString("trade_id"))
   var timer:String?=null
   if(!snapshot.getBoolean("legacy") && o.side=="buy" && !snapshot.getJSONObject("policy").isNull("entry_timeout_seconds") && remote.getString("status") !in terminal) {
    val key="timer:${o.client}"; val old=journal.meta(key)
    val acknowledged=if(old.isBlank()) JSONObject().put("session",timerSession).put("mono",monotonic()) else JSONObject(old)
    val elapsed=monotonic()-acknowledged.getLong("mono")
    if((old.isBlank() && o.broker.isNotBlank() && o.client !in submittedHere) || acknowledged.getString("session")!=timerSession || elapsed<0 || elapsed>=snapshot.getJSONObject("policy").getInt("entry_timeout_seconds")*1000L) journal.setMeta("entry_closed:${e.getString("trade_id")}","true")
    timer=acknowledged.toString()
   }
   journal.updateObserved(o.client,remote,timer)
   if(timer!=null) submittedHere.remove(o.client)
   freshlyReconciled.add(o.client)
   } catch(error:Exception) {
    if(error is InterruptedException) { Thread.currentThread().interrupt(); throw error }
    if(error is Superseded || error is java.util.concurrent.CancellationException) throw error
    BrokerLifecycleFence.interrupted()
    healthy=false; if(reconciliationError==null) reconciliationError=error
    journal.diagnostic(e.getString("event_id"),"reconciliation_error","Broker evidence unavailable or invalid for ${o.client}; new submissions blocked")
   }
  }
  reconciliationHealthy=healthy; return healthy
 }
}

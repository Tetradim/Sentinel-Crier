package com.sentinel.crier
import android.content.Context
import android.content.ContextWrapper
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
internal class RouteRuntime(context:Context,override val routeId:String,private val gate:ExecutionStartGate,private val finished:()->Unit):ContextWrapper(context), RouteOwner {
 override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences(RouteStorage.preferences(name,routeId),mode)
 private val pool=Executors.newFixedThreadPool(7)
 @Volatile private var running=true
 @Volatile private var push:PushConnection?=null
 @Volatile private var transport="connecting"
 private var health:ComponentHealth?=null
 private var healthTicket:ComponentHealth.Ticket?=null
 private fun note(component:String,state:String,reason:String) { healthTicket?.let { reportHealth(health?.observer(it),component,state,reason) } }
 fun startWorkers() {
  val config=Vault(this).read(); val journal=Journal(this)
  require(routeId==RouteStorage.sharedFeatureRoute(this) || config.optString("authMode")!="oauth") { "Customer OAuth is available only on the original legacy route; reconnect this route with Alpaca API keys" }
  health=AppHealth.ledger(this)
  val components=mutableSetOf("broker","execution",if(config.optString("role")=="host") "relay_send" else "relay_receive")
  if(config.optString("discordWebhook").isNotBlank()) components.add("discord")
  healthTicket=health?.begin(ComponentHealth.scope(config,"intent"),components,"intent")
  journal.setMeta("service","Reconnecting · reconciling before new work")
  if(!config.has("account")) { stop(); return }
  val customerSession=EncryptedCustomerSessions(this).read()
  val customerService=runCatching { CustomerOAuth.sibling(QuickConnection.defaultOrigin(this)) }.getOrDefault("")
  if(config.optString("authMode")=="oauth" && (customerSession.optString("service")!=customerService || config.optString("bearer").isBlank() || config.optString("oauthPurpose")!="trade" || !OAuthProvenance.matches(config,customerSession.optString("owner"),customerService))) { journal.setMeta("status","Sign in as the saved customer and reconnect brokerage before starting"); stop(); return }
  val url=config.getString("url").trimEnd('/'); val headers=mapOf("Authorization" to "Bearer ${config.getString("token")}")
  fun worker(component:String?=null,task:()->Unit) { pool.submit { while(running) { try { task() } catch(e:Exception) { if(running && component!=null) note(component,if(e is HttpError && e.status in setOf(401,403)) "blocked" else "degraded",if(e is HttpError && e.status in setOf(401,403)) "authentication_failed" else "connection_failed"); journal.setMeta("status",e.message ?: "Connection error"); journal.setMeta("connection",if(e is HttpError && e.status in setOf(401,403)) "Authentication failed; stop workers and restore credentials / connection" else "Disconnected / retrying; review status"); try { Thread.sleep(2000) } catch(_:InterruptedException) { return@submit } } } } }
  fun currentScope()=running && gate.permits(this) && Settings.sameIdentity(config,Vault(this).read())
  fun consume(response:org.json.JSONObject) {
   check(currentScope())
   if(config.getString("role")!="follower") return
   var invalid=false
   IncomingProtocol.consume(response.getJSONArray("events"),config.getString("environment"),{ journal.meta("cursor").toLongOrNull() ?: 0 },{ event,cursor ->
    check(currentScope()); journal.accept(event,cursor=cursor,skipEntry=getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)); JournalWakes.execution.wake(); JournalWakes.telemetry.wake()
   },{ cursor,reason -> invalid=true; journal.reject(cursor,reason) })
   note("relay_receive",if(invalid) "degraded" else "healthy",if(invalid) "invalid_events" else "checked")
  }
  worker("relay_receive") {
   check(currentScope()); val stream=PushConnection(); push=stream; transport="connecting"
   try {
    stream.read("$url/api/sync/stream?after=${journal.meta("cursor").ifBlank { "0" }}",headers,::currentScope) { event,body ->
     check(currentScope())
     when(event) {
      "ready" -> { require(body.getInt("version")==1 && body.getString("transport")=="push"); transport="push"; JournalWakes.telemetry.wake() }
      "events" -> consume(body)
      "dashboard" -> CopyDashboardCache.accept(config,body)
      "heartbeat" -> require(body.get("server_time_ms") is Number)
     }
     journal.setMeta("connection","Connected · $transport · ${java.time.Instant.now()}")
    }
   } catch(error:Exception) {
    if(!currentScope()) throw error
    transport="poll"; JournalWakes.telemetry.wake()
    if(config.getString("role")=="follower") consume(Network.request("$url/api/sync/events?after=${journal.meta("cursor").ifBlank { "0" }}&wait=20",headers=headers))
    else { CopyDashboardCache.accept(config,Network.request("$url/api/sync/dashboard",headers=headers)); Thread.sleep(2000) }
    journal.setMeta("connection","Connected · poll · ${java.time.Instant.now()}")
   } finally { stream.close(); if(push===stream) push=null }
  }
  val reporter=CopyReporter(journal) { route,body -> check(currentScope()); Network.request("$url/api/sync/$route","POST",headers,body); check(currentScope()) }
  worker { try { reporter.tick(transport,getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) } catch(_:Exception) { journal.setMeta("copyTelemetry","Telemetry unavailable; execution remains independent") }; JournalWakes.telemetry.await(15000) }
  worker("relay_send") {
   if(config.getString("role")=="host" && journal.events(true).isEmpty()) note("relay_send","idle","no_work")
   if(config.getString("role")=="host") for(e in journal.events(true).sortedBy { if(it.getString("action") in setOf("cancel","exit")) 0 else 1 }) {
    val revision=journal.revision(e.getString("trade_id")); if(e.getString("action") in setOf("enter","replace") && (revision.second || e.getInt("sequence")<revision.first || java.time.Instant.now()>java.time.Instant.parse(e.getString("expires_at")))) { journal.mark(e.getString("event_id"),true); continue }
    try { Network.request("$url/api/sync/events","POST",headers,e); journal.evidence(e.getString("event_id"),"relay_ack"); journal.mark(e.getString("event_id"),true); note("relay_send","healthy","delivered"); journal.setMeta("connection","Connected · last publish ${java.time.Instant.now()}") }
    catch(error:HttpError) { if(error.status in setOf(400,409,422)) { journal.diagnostic(e.getString("event_id"),"relay_rejected","HTTP ${error.status}; rejected event retained in history"); journal.mark(e.getString("event_id"),true); journal.setMeta("connection","Publish rejected HTTP ${error.status}; see diagnostics") } else throw error }
   }
   JournalWakes.outbox.await(1000)
  }
  val diagnostics=Diagnostics(journal,config)
  worker { diagnostics.tick(); Thread.sleep(250) }
  val rawBroker=Broker(config)
  val metadataRetry=MetadataRetry { android.os.SystemClock.elapsedRealtime() }
  worker {
   for(event in journal.history().take(50)) {
    if(!currentScope()) break
    val id=event.getString("trade_id")
    metadataRetry.resolve(id,::currentScope,{ rawBroker.binding(event) }) { binding ->
     journal.setMeta("copyBinding:$id",binding.toString()); JournalWakes.telemetry.wake()
    }
   }
   Thread.sleep(15000)
  }
  val mutationFence=BrokerLifecycleFence(config,{ running && gate.permits(this) },{ Vault(this).read() },{ EncryptedCustomerSessions(this).read() },customerService)
  fun dispatchAllowed(event:org.json.JSONObject,sell:Boolean):Boolean = running && runCatching {
   mutationFence.check()
   val saved=Vault(this).read(); require(Settings.sameIdentity(config,saved)); require(listOf("mode","bps","amount").all { config.optString(it)==saved.optString(it) }); if(!sell) require(event.getInt("quantity")<=saved.optInt("maxQuantity",1000))
   if(config.optString("authMode")=="oauth") { val session=EncryptedCustomerSessions(this).read(); require(OAuthProvenance.matches(saved,session.optString("owner"),customerService) && saved.optString("bearer")==config.optString("bearer")) }; true
  }.getOrDefault(false)
  val observedBroker=object:BrokerPort by rawBroker {
   override fun cancel(id:String) { mutationFence.check(); rawBroker.cancel(id) }
   override fun submit(event:org.json.JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean)=rawBroker.submit(event,client,quantity,sell) { dispatchAllowed(event,sell) && canSubmit() }
   override fun submitPlanned(event:org.json.JSONObject,client:String,quantity:Int,sell:Boolean,plan:org.json.JSONObject,canSubmit:()->Boolean)=rawBroker.submitPlanned(event,client,quantity,sell,plan) { dispatchAllowed(event,sell) && canSubmit() }

   override fun account():String {
    try { val id=rawBroker.account(); require(id==config.getString("account")) { "Account changed" }; note("broker","healthy","verified"); return id }
    catch(error:Exception) { note("broker","blocked",if(error is HttpError && error.status in setOf(401,403)) "authentication_failed" else "reconciliation_required"); throw error }
   }
  }
  val engine=Engine(journal,config,broker=observedBroker,entryClock=EntryClock(mono={android.os.SystemClock.elapsedRealtime()})) { getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true) }
  var reconciled=false
  worker("execution") {
   var needsReconciliation=false
   if(!reconciled) {
    require(observedBroker.account()==config.getString("account")) { "Account changed; execution blocked" }
    for(e in journal.events(false)) if(!engine.reconcile(e)) needsReconciliation=true
    reconciled=true; journal.setMeta("service","Running · resume reconciliation completed")
   }
   for(e in journal.events(false)) { try { engine.step(e); if(!engine.reconciliationHealthy) needsReconciliation=true } catch(error:Exception) { engine.reconnect(); needsReconciliation=true; journal.diagnostic(e.getString("event_id"),"reconciliation_error",if(error is HttpError) "HTTP ${error.status}" else "Broker reconciliation needs attention"); journal.setMeta("status","Reconciliation needed: ${error.message}") } }
   note("execution",if(needsReconciliation) "blocked" else "healthy",if(needsReconciliation) "reconciliation_required" else "checked")
   JournalWakes.execution.await(300)
  }
  worker("discord") {
   OAuthProvenance.requireDestination(config,EncryptedCustomerSessions(this).read(),customerService)
   Discord.deliver(journal,config,observe=healthTicket?.let { health?.observer(it) },send={ destination,body ->
    check(running) { "Workers stopped before publishing" }
    OAuthProvenance.requireDestination(config,EncryptedCustomerSessions(this).read(),customerService)
    Network.request(destination,"POST",body=body)
   }); Thread.sleep(1000)
  }
 }
 @Synchronized fun stop() { if(!running) return; running=false; gate.stop(); push?.close(); JournalWakes.execution.wake(); JournalWakes.outbox.wake(); JournalWakes.telemetry.wake(); pool.shutdownNow(); Thread { while(!pool.awaitTermination(1,TimeUnit.SECONDS)) {} ; try { Journal(this).use { it.setMeta("service","Workers stopped · reconnect to reconcile and resume") } } finally { healthTicket?.let { health?.stop(it) }; gate.drained(this@RouteRuntime); finished() } }.start() }
}

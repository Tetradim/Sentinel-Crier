package com.sentinel.crier
import android.app.*
import android.content.Intent
import android.os.IBinder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
class SyncService: Service() {
 companion object {
  private val gate=ExecutionStartGate()
  val active:Boolean get()=gate.active
  val authClosing:Boolean get()=gate.closing
  const val EXPLICIT_START="com.sentinel.crier.EXPLICIT_EXECUTION_START"
  fun acceptsStart(action:String?)=action==EXPLICIT_START
  fun requestStart(context:android.content.Context) {
   val ticket=gate.reserve()
   try { context.startForegroundService(Intent(context,SyncService::class.java).setAction(EXPLICIT_START).putExtra("admission",ticket)) }
   catch(error:Exception) { gate.abandon(ticket); throw error }
  }
  fun stopRequests() { gate.stop() }
  fun beginAuthStop() { gate.stop(true) }
  fun finishAuthStop() { gate.finishLogout() }
 }
 private var started=false
 private val pool=Executors.newFixedThreadPool(5)
 @Volatile private var running=true
 private var health:ComponentHealth?=null
 private var healthTicket:ComponentHealth.Ticket?=null
 private fun note(component:String,state:String,reason:String) { healthTicket?.let { reportHealth(health?.observer(it),component,state,reason) } }
 override fun onBind(intent:Intent?):IBinder?=null
 override fun onCreate() { super.onCreate() }
 private fun startWorkers() {
  started=true
  val manager=getSystemService(NotificationManager::class.java)
  manager.createNotificationChannel(NotificationChannel("sync","Crier execution",NotificationManager.IMPORTANCE_LOW))
  val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
  startForeground(1,Notification.Builder(this,"sync").setContentTitle("Crier running").setContentText("Open to pause entries or review status").setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(open).build())
  val config=Vault(this).read(); val journal=Journal(this)
  health=AppHealth.ledger(this)
  val components=mutableSetOf("broker","execution",if(config.optString("role")=="host") "relay_send" else "relay_receive")
  if(config.optString("discordWebhook").isNotBlank()) components.add("discord")
  healthTicket=health?.begin(ComponentHealth.scope(config,"intent"),components,"intent")
  journal.setMeta("service","Reconnecting Â· reconciling before new work")
  if(!config.has("account")) { stopSelf(); return }
  val customerSession=EncryptedCustomerSessions(this).read()
  val customerService=runCatching { CustomerOAuth.sibling(QuickConnection.defaultOrigin(this)) }.getOrDefault("")
  if(config.optString("authMode")=="oauth" && (customerSession.optString("service")!=customerService || config.optString("bearer").isBlank() || config.optString("oauthPurpose")!="trade" || !OAuthProvenance.matches(config,customerSession.optString("owner"),customerService))) { journal.setMeta("status","Sign in as the saved customer and reconnect brokerage before starting"); stopSelf(); return }
  val url=config.getString("url").trimEnd('/'); val headers=mapOf("Authorization" to "Bearer ${config.getString("token")}")
  fun worker(component:String?=null,task:()->Unit) { pool.submit { while(running) { try { task() } catch(e:Exception) { if(running && component!=null) note(component,if(e is HttpError && e.status in setOf(401,403)) "blocked" else "degraded",if(e is HttpError && e.status in setOf(401,403)) "authentication_failed" else "connection_failed"); journal.setMeta("status",e.message ?: "Connection error"); journal.setMeta("connection",if(e is HttpError && e.status in setOf(401,403)) "Authentication failed; stop workers and restore credentials / connection" else "Disconnected / retrying; review status"); try { Thread.sleep(2000) } catch(_:InterruptedException) { return@submit } } } } }
  worker("relay_receive") {
   if(config.getString("role")=="follower") {
    val response=Network.request("$url/api/sync/events?after=${journal.meta("cursor").ifBlank { "0" }}&wait=20",headers=headers)
    val events=response.getJSONArray("events")
    var invalid=false
    IncomingProtocol.consume(events,config.getString("environment"),{ journal.meta("cursor").toLongOrNull() ?: 0 },{ event,cursor -> journal.accept(event,cursor=cursor,skipEntry=getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) },{ cursor,reason -> invalid=true; journal.reject(cursor,reason) })
    note("relay_receive",if(invalid) "degraded" else "healthy",if(invalid) "invalid_events" else "checked")
    journal.setMeta("connection","Connected Â· last checked ${java.time.Instant.now()}")
   } else Thread.sleep(1000)
  }
  worker("relay_send") {
   if(config.getString("role")=="host" && journal.events(true).isEmpty()) note("relay_send","idle","no_work")
   if(config.getString("role")=="host") for(e in journal.events(true).sortedBy { if(it.getString("action") in setOf("cancel","exit")) 0 else 1 }) {
    val revision=journal.revision(e.getString("trade_id")); if(e.getString("action") in setOf("enter","replace") && (revision.second || e.getInt("sequence")<revision.first || java.time.Instant.now()>java.time.Instant.parse(e.getString("expires_at")))) { journal.mark(e.getString("event_id"),true); continue }
    try { Network.request("$url/api/sync/events","POST",headers,e); journal.evidence(e.getString("event_id"),"relay_ack"); journal.mark(e.getString("event_id"),true); note("relay_send","healthy","delivered"); journal.setMeta("connection","Connected Â· last publish ${java.time.Instant.now()}") }
    catch(error:HttpError) { if(error.status in setOf(400,409,422)) { journal.diagnostic(e.getString("event_id"),"relay_rejected","HTTP ${error.status}; rejected event retained in history"); journal.mark(e.getString("event_id"),true); journal.setMeta("connection","Publish rejected HTTP ${error.status}; see diagnostics") } else throw error }
   }
   Thread.sleep(100)
  }
  val diagnostics=Diagnostics(journal,config)
  worker { diagnostics.tick(); Thread.sleep(250) }
  val rawBroker=Broker(config)
  val observedBroker=object:BrokerPort by rawBroker {
   override fun account():String {
    try { val id=rawBroker.account(); require(id==config.getString("account")) { "Account changed" }; note("broker","healthy","verified"); return id }
    catch(error:Exception) { note("broker","blocked",if(error is HttpError && error.status in setOf(401,403)) "authentication_failed" else "reconciliation_required"); throw error }
   }
  }
  val engine=Engine(journal,config,broker=observedBroker) { getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true) }
  var reconciled=false
  worker("execution") {
   var needsReconciliation=false
   if(!reconciled) {
    require(observedBroker.account()==config.getString("account")) { "Account changed; execution blocked" }
    for(e in journal.events(false)) if(!engine.reconcile(e)) needsReconciliation=true
    reconciled=true; journal.setMeta("service","Running Â· resume reconciliation completed")
   }
   for(e in journal.events(false)) { try { engine.step(e); if(!engine.reconciliationHealthy) needsReconciliation=true } catch(error:Exception) { needsReconciliation=true; journal.diagnostic(e.getString("event_id"),"reconciliation_error",if(error is HttpError) "HTTP ${error.status}" else "Broker reconciliation needs attention"); journal.setMeta("status","Reconciliation needed: ${error.message}") } }
   note("execution",if(needsReconciliation) "blocked" else "healthy",if(needsReconciliation) "reconciliation_required" else "checked")
   Thread.sleep(300)
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
 override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
  if(!acceptsStart(intent?.action)) { if(!started) stopSelf(); return START_NOT_STICKY }
  if(!started) {
   val enabled=getSharedPreferences("controls",MODE_PRIVATE).getBoolean("enabled",false)
   if(!gate.claim(intent?.getLongExtra("admission",-1) ?: -1,this,enabled)) { stopSelf(); return START_NOT_STICKY }
   startWorkers()
  }
  return START_NOT_STICKY
 }
 override fun onTimeout(startId:Int,fgsType:Int) { gate.stop(); getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit(); Journal(this).setMeta("service","Background sync timed out Â· entries paused. Open Crier and reconnect; broker reconciliation runs before new work."); stopSelf() }
 override fun onDestroy() { running=false; pool.shutdownNow(); Thread { while(!pool.awaitTermination(1,TimeUnit.SECONDS)) {} ; try { if(started) { val journal=Journal(this); if(!journal.meta("service").startsWith("Background sync timed out")) journal.setMeta("service","Workers stopped · reconnect to reconcile and resume"); journal.close() } } finally { healthTicket?.let { health?.stop(it) }; gate.drained(this@SyncService) } }.start(); super.onDestroy() }
}

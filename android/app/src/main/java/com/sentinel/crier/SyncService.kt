package com.sentinel.crier
import android.app.*
import android.content.Intent
import android.os.IBinder
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
class SyncService: Service() {
 companion object { @Volatile var active=false; private set }
 private val pool=Executors.newFixedThreadPool(5)
 @Volatile private var running=true
 override fun onBind(intent:Intent?):IBinder?=null
 override fun onCreate() {
  super.onCreate(); synchronized(SyncService::class.java) { active=true }
  val manager=getSystemService(NotificationManager::class.java)
  manager.createNotificationChannel(NotificationChannel("sync","Crier execution",NotificationManager.IMPORTANCE_LOW))
  val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
  startForeground(1,Notification.Builder(this,"sync").setContentTitle("Crier running").setContentText("Open to pause entries or review status").setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(open).build())
  val config=Vault(this).read(); val journal=Journal(this)
  journal.setMeta("service","Reconnecting Â· reconciling before new work")
  if(!config.has("account")) { stopSelf(); return }
  val url=config.getString("url").trimEnd('/'); val headers=mapOf("Authorization" to "Bearer ${config.getString("token")}")
  fun worker(task:()->Unit) { pool.submit { while(running) { try { task() } catch(e:Exception) { journal.setMeta("status",e.message ?: "Connection error"); journal.setMeta("connection",if(e is HttpError && e.status in setOf(401,403)) "Authentication failed; stop workers and restore credentials / connection" else "Disconnected / retrying; review status"); try { Thread.sleep(2000) } catch(_:InterruptedException) { return@submit } } } } }
  worker {
   if(config.getString("role")=="follower") {
    val response=Network.request("$url/api/sync/events?after=${journal.meta("cursor").ifBlank { "0" }}&wait=20",headers=headers)
    val events=response.getJSONArray("events")
    IncomingProtocol.consume(events,config.getString("environment"),{ journal.meta("cursor").toLongOrNull() ?: 0 },{ event,cursor -> journal.accept(event,cursor=cursor,skipEntry=getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) },journal::reject)
    journal.setMeta("connection","Connected Â· last checked ${java.time.Instant.now()}")
   } else Thread.sleep(1000)
  }
  worker {
   if(config.getString("role")=="host") for(e in journal.events(true).sortedBy { if(it.getString("action") in setOf("cancel","exit")) 0 else 1 }) {
    val revision=journal.revision(e.getString("trade_id")); if(e.getString("action") in setOf("enter","replace") && (revision.second || e.getInt("sequence")<revision.first || java.time.Instant.now()>java.time.Instant.parse(e.getString("expires_at")))) { journal.mark(e.getString("event_id"),true); continue }
    try { Network.request("$url/api/sync/events","POST",headers,e); journal.evidence(e.getString("event_id"),"relay_ack"); journal.mark(e.getString("event_id"),true); journal.setMeta("connection","Connected Â· last publish ${java.time.Instant.now()}") }
    catch(error:HttpError) { if(error.status in setOf(400,409,422)) { journal.diagnostic(e.getString("event_id"),"relay_rejected","HTTP ${error.status}; rejected event retained in history"); journal.mark(e.getString("event_id"),true); journal.setMeta("connection","Publish rejected HTTP ${error.status}; see diagnostics") } else throw error }
   }
   Thread.sleep(100)
  }
  val diagnostics=Diagnostics(journal,config)
  worker { diagnostics.tick(); Thread.sleep(250) }
  val engine=Engine(journal,config) { getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true) }
  var reconciled=false
  worker {
   if(!reconciled) {
    require(Broker(config).account()==config.getString("account")) { "Account changed; execution blocked" }
    for(e in journal.events(false)) engine.reconcile(e)
    reconciled=true; journal.setMeta("service","Running Â· resume reconciliation completed")
   }
   for(e in journal.events(false)) { try { engine.step(e) } catch(error:Exception) { journal.diagnostic(e.getString("event_id"),"reconciliation_error",if(error is HttpError) "HTTP ${error.status}" else "Broker reconciliation needs attention"); journal.setMeta("status","Reconciliation needed: ${error.message}") } }
   Thread.sleep(300)
  }
  worker { Discord.deliver(journal,config); Thread.sleep(1000) }
 }
 override fun onStartCommand(intent:Intent?,flags:Int,startId:Int)=START_STICKY
 override fun onTimeout(startId:Int,fgsType:Int) { getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit(); Journal(this).setMeta("service","Background sync timed out Â· entries paused. Open Crier and reconnect; broker reconciliation runs before new work."); stopSelf() }
 override fun onDestroy() { running=false; pool.shutdownNow(); Thread { while(!pool.awaitTermination(1,TimeUnit.SECONDS)) {} ; try { val journal=Journal(this); if(!journal.meta("service").startsWith("Background sync timed out")) journal.setMeta("service","Workers stopped · reconnect to reconcile and resume"); journal.close() } finally { synchronized(SyncService::class.java) { active=false } } }.start(); super.onDestroy() }
}

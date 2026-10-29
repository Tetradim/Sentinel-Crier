package com.sentinel.crier
import android.app.*
import android.content.Context
import android.content.Intent
import android.os.IBinder
class SyncService:Service() {
 companion object {
  private val gates=mutableMapOf<String,ExecutionStartGate>()
  private val reservations=mutableMapOf<String,String>()
  @Volatile private var service:SyncService?=null
  @Volatile private var closing=false
  @Synchronized private fun gate(id:String)=gates.getOrPut(id) { ExecutionStartGate() }
  val active:Boolean get()=synchronized(this) { gates.values.any { it.active } }
  val authClosing:Boolean get()=closing
  fun active(context:Context)=gate(RouteStorage.id(context)).active
  const val EXPLICIT_START="com.sentinel.crier.EXPLICIT_EXECUTION_START"
  fun acceptsStart(action:String?)=action==EXPLICIT_START
  fun requestStart(context:Context) {
   check(!closing) { "Sign out is stopping workers" }
   val id=RouteStorage.id(context); val config=Vault(context).read()
   RouteAccounts.requireAvailable(id,config,Vault(context).profiles().map { it.getString("id") to it.getJSONObject("config") })
   val account=RouteStorage.accountKey(config)
   val ticket=synchronized(this) {
   check(!closing) { "Sign out is stopping workers" }
   require(reservations[account]==null || reservations[account]==id) { "This broker account and environment already belong to another running route. Stop it first." }
   reservations[account]=id
   gate(id).reserve()
   }
   try { context.startForegroundService(Intent(context,SyncService::class.java).setAction(EXPLICIT_START).putExtra("route",id).putExtra("admission",ticket)) }
   catch(error:Exception) { gate(id).abandon(ticket); release(id); throw error }
  }
  fun stopRequests(context:Context) { val id=RouteStorage.id(context); gate(id).stop(); service?.stopRoute(id) }
  @Synchronized fun stopRequests() { gates.values.forEach { it.stop() }; service?.stopAll() }
  fun beginAuthStop() { closing=true; stopRequests() }
  @Synchronized fun finishAuthStop() { check(!active); gates.values.forEach { it.finishLogout() }; closing=false }
  @Synchronized private fun release(id:String) { reservations.entries.removeAll { it.value==id } }
 }
 private val sessions=mutableMapOf<String,RouteRuntime>()
 override fun onBind(intent:Intent?):IBinder?=null
 override fun onCreate() { super.onCreate(); service=this }
 override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
  if(!acceptsStart(intent?.action)) { if(sessions.isEmpty()) stopSelf(); return START_NOT_STICKY }
  val id=intent?.getStringExtra("route") ?: return START_NOT_STICKY
  if(sessions.containsKey(id)) return START_NOT_STICKY
  val context=RouteContext(this,id); val admission=gate(id)
  lateinit var runtime:RouteRuntime
  runtime=RouteRuntime(this,id,admission) { android.os.Handler(mainLooper).post { sessions.remove(id); release(id); if(sessions.isEmpty()) stopSelf() } }
  if(!admission.claim(intent.getLongExtra("admission",-1),runtime,context.getSharedPreferences("controls",MODE_PRIVATE).getBoolean("enabled",false))) { release(id); if(sessions.isEmpty()) stopSelf(); return START_NOT_STICKY }
  sessions[id]=runtime
  val manager=getSystemService(NotificationManager::class.java)
  manager.createNotificationChannel(NotificationChannel("sync","Crier execution",NotificationManager.IMPORTANCE_LOW))
  val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
  startForeground(1,Notification.Builder(this,"sync").setContentTitle("Crier routes running").setContentText("Open to select a route and pause entries").setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(open).build())
  try { runtime.startWorkers() } catch(error:Exception) { Journal(context).use { it.setMeta("status",error.message ?: "Start blocked") }; runtime.stop() }
  return START_NOT_STICKY
 }
 private fun stopRoute(id:String) { android.os.Handler(mainLooper).post { sessions[id]?.stop() ?: release(id) } }
 private fun stopAll() { android.os.Handler(mainLooper).post { sessions.values.toList().forEach { runtime -> runtime.getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit(); runtime.stop() } } }
 override fun onTimeout(startId:Int,fgsType:Int) { stopRequests(); stopSelf() }
 override fun onDestroy() { stopAll(); service=null; super.onDestroy() }
}

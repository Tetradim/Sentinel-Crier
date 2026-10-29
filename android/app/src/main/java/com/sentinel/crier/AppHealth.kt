package com.sentinel.crier

import android.content.Context
import org.json.JSONObject

object AppHealth {
 private val instances=mutableMapOf<String,ComponentHealth>()
 private val disk=java.util.concurrent.Executors.newSingleThreadExecutor { task -> Thread(task,"Crier health persistence").apply { isDaemon=true } }
 @Synchronized fun ledger(context:Context):ComponentHealth=instances[RouteStorage.id(context)] ?: run {
  runCatching {
   val prefs=context.getSharedPreferences("component-health",Context.MODE_PRIVATE)
   lateinit var ledger:ComponentHealth
   val persistence=HealthPersistence({prefs.edit().putString("history",it).commit()},{ledger.persistenceResult(it)},{task -> disk.execute(task)})
   ledger=ComponentHealth({JSONObject(prefs.getString("history","{}") ?: "{}")},{persistence.enqueue(it.toString())},mono={android.os.SystemClock.elapsedRealtime()})
   ledger
  }.getOrElse { ComponentHealth({error("Health storage unavailable")}) }.also { instances[RouteStorage.id(context)]=it }
 }
}

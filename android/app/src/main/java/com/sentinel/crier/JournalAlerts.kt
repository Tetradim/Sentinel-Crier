package com.sentinel.crier

import android.database.sqlite.SQLiteDatabase
import org.json.JSONObject

/** Alert outbox persistence. Journal owns synchronization; claim and status stay transactional. */
internal class JournalAlerts(private val database:()->SQLiteDatabase,private val setMeta:(String,String)->Unit) {
 fun enqueueAlert(id:String,payload:JSONObject) { database().execSQL("INSERT OR IGNORE INTO alerts(id,payload) VALUES(?,?)",arrayOf(id,payload.toString())) }
 fun alert(now:Long,id:String?=null):JSONObject? = database().rawQuery("SELECT id,payload,attempts FROM alerts WHERE state='pending' AND next<=?"+(if(id!=null) " AND id=?" else "")+" ORDER BY rowid LIMIT 1",if(id!=null) arrayOf(now.toString(),id) else arrayOf(now.toString())).use { if(it.moveToFirst()) JSONObject().put("id",it.getString(0)).put("payload",JSONObject(it.getString(1))).put("attempts",it.getInt(2)) else null }
 fun claimAlert(now:Long,id:String?):JSONObject? {
  val db=database(); db.beginTransaction()
  try { val next=alert(now,id); if(next!=null) { db.execSQL("UPDATE alerts SET state='uncertain',attempts=attempts+1,detail='Dispatch reserved; acknowledgement pending' WHERE id=?",arrayOf(next.getString("id"))); setMeta("discordStatus","Dispatch reserved; acknowledgement pending. Inspect Discord before retrying.") }; db.setTransactionSuccessful(); return next }
  finally { db.endTransaction() }
 }
 fun alertResult(id:String,state:String,delay:Long,detail:String) { database().execSQL("UPDATE alerts SET state=?,next=?,detail=? WHERE id=?",arrayOf(state,System.currentTimeMillis()+delay,detail,id)); setMeta("discordStatus","$state: $detail") }
 fun healthStates():Set<String> = database().rawQuery("SELECT DISTINCT state FROM alerts WHERE state NOT IN ('delivered','discarded')",null).use { c -> buildSet { while(c.moveToNext()) add(c.getString(0)) } }
 fun hasUndeliveredAlerts():Boolean = database().rawQuery("SELECT COUNT(*) FROM alerts WHERE state IN ('pending','blocked','uncertain')",null).use { it.moveToFirst(); it.getInt(0)>0 }
 fun discardAlerts() { database().execSQL("UPDATE alerts SET state='discarded',detail='Explicitly discarded by user before destination change' WHERE state IN ('pending','blocked','uncertain')") }
 fun retryAlerts() { database().execSQL("UPDATE alerts SET state='pending',next=0 WHERE state IN ('pending','blocked','uncertain')") }
 fun alertSummary():String = database().rawQuery("SELECT state,COUNT(*) FROM alerts GROUP BY state",null).use { c -> buildList { while(c.moveToNext()) add("${c.getString(0)}: ${c.getInt(1)}") }.joinToString(", ").ifBlank { "No queued messages" } }
}

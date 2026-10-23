package com.sentinel.crier
import org.json.JSONArray
import org.json.JSONObject

/** Invalid payloads are quarantined durably before advancing; transport/envelope faults remain visible. */
object IncomingProtocol {
 fun consume(rows:JSONArray,environment:String,after:()->Long,accept:(JSONObject,Long)->Unit,reject:(Long,String)->Unit) {
  for(i in 0 until rows.length()) {
   val row=rows.getJSONObject(i); val cursor=row.getLong("cursor")
   require(cursor>0 && row.get("cursor").toString()==cursor.toString()) { "Invalid relay cursor; reconnect required" }
   if(cursor<=after()) continue
   val event=try { row.getJSONObject("event").also { Journal.validate(it,environment) } }
   catch(error:Exception) {
    if(error !is IllegalArgumentException && error !is org.json.JSONException && error !is java.time.DateTimeException) throw error
    reject(cursor,"Malformed instruction fields"); continue
   }
   try { accept(event,cursor) }
   catch(error:IllegalArgumentException) { reject(cursor,"Conflicting instruction revision or trade identity") }
  }
 }
 fun sameEvent(a:JSONObject,b:JSONObject)=a.keys().asSequence().toSet()==b.keys().asSequence().toSet() && a.keys().asSequence().all { a.get(it)==b.get(it) }
}

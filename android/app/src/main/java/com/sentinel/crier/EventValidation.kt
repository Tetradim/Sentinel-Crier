package com.sentinel.crier

import org.json.JSONObject
import java.time.Instant
import java.util.UUID

/** Canonical event boundary used by receipt and locally created intents. */
object EventValidation {
  fun validate(e:JSONObject,environment:String) {
   require(e.keys().asSequence().toSet()==setOf("version","event_id","trade_id","sequence","action","environment","symbol","asset","quantity","limit_price","created_at","expires_at"))
   require(e.getInt("version")==1 && e.get("version").toString()=="1" && e.getString("environment")==environment)
   for(k in listOf("event_id","trade_id")) require(UUID.fromString(e.getString(k)).toString()==e.getString(k))
   require(e.get("sequence").toString()==e.getInt("sequence").toString() && e.getInt("sequence")>0 && e.getString("action") in setOf("enter","replace","cancel","exit"))
   require(e.getString("asset") in setOf("stock","option") && e.getString("symbol").matches(if(e.getString("asset")=="option") Regex("[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}") else Regex("[A-Z][A-Z0-9.]{0,14}")))
   if(e.getString("asset")=="option") { val symbol=e.getString("symbol"); val date=symbol.takeLast(15).take(6); java.time.LocalDate.of(2000+date.take(2).toInt(),date.substring(2,4).toInt(),date.takeLast(2).toInt()); require(symbol.takeLast(8).toLong()>0) }
   require(e.get("quantity").toString()==e.getInt("quantity").toString() && e.getInt("quantity") in 1..1000 && e.get("limit_price") is String && e.getString("limit_price").toBigDecimal().signum()>0)
   val created=Instant.parse(e.getString("created_at")); val expires=Instant.parse(e.getString("expires_at"))
   require(expires>=created && (e.getString("action") !in setOf("enter","replace") || expires<=created.plusSeconds(30)))
  }
}

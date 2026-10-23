package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONTokener
import java.net.HttpURLConnection
import java.net.URI
class Superseded:Exception("Intent superseded before broker submission")
class HttpError(val status: Int, val retryAfter:Long=0): Exception("HTTP $status")
object Network {
 fun request(url: String, method: String = "GET", headers: Map<String,String> = emptyMap(), body: JSONObject? = null): JSONObject = requestValue(url,method,headers,body) as JSONObject
 fun requestValue(url: String, method: String = "GET", headers: Map<String,String> = emptyMap(), body: JSONObject? = null): Any {
  val uri = URI(url); require(uri.scheme == "https" && uri.userInfo == null)
  val conn = uri.toURL().openConnection() as HttpURLConnection
  conn.requestMethod = method; conn.connectTimeout = 15000; conn.readTimeout = 30000; conn.instanceFollowRedirects = false
  headers.forEach { (k,v) -> conn.setRequestProperty(k,v) }
  try {
   if (body != null) { conn.doOutput = true; conn.setRequestProperty("Content-Type", "application/json"); conn.outputStream.use { it.write(body.toString().toByteArray()) } }
   val status = conn.responseCode
   if (status !in 200..299) throw HttpError(status,conn.getHeaderField("Retry-After")?.toDoubleOrNull()?.let { kotlin.math.ceil(it).toLong() } ?: 0)
   val text = conn.inputStream.bufferedReader().use { it.readText() }
   return if (text.isBlank()) JSONObject() else JSONTokener(text).nextValue()
  } finally { conn.disconnect() }
 }
}
class Broker(private val config: JSONObject): BrokerPort {
 private val base = if(config.getString("environment") == "paper") "https://paper-api.alpaca.markets" else "https://api.alpaca.markets"
 private val headers = mapOf("APCA-API-KEY-ID" to config.getString("key"), "APCA-API-SECRET-KEY" to config.getString("secret"))
 override fun account():String { val a=Network.request("$base/v2/account", headers=headers); require(a.getString("status")=="ACTIVE" && !a.optBoolean("trading_blocked",true) && !a.optBoolean("account_blocked",true)) { "Broker account is not active for trading" }; return a.getString("id") }
 override fun order(client: String): JSONObject? = try { Network.request("$base/v2/orders:by_client_order_id?client_order_id=$client", headers=headers) } catch(e: HttpError) { if(e.status == 404) null else throw e }
 override fun cancel(id: String) { try { Network.request("$base/v2/orders/$id", "DELETE", headers) } catch(e: HttpError) { if(e.status !in setOf(404,422)) throw e } }
 override fun holdings(symbol: String): Int = try { Network.request("$base/v2/positions/$symbol", headers=headers).optString("qty_available", "0").toBigDecimal().toInt().coerceAtLeast(0) } catch(e: HttpError) { if(e.status==404) 0 else throw e }
 override fun submit(event: JSONObject, client: String, quantity: Int, sell: Boolean, canSubmit:()->Boolean): JSONObject {
  if(event.getString("asset")=="option") { val contract=Network.request("$base/v2/options/contracts/${event.getString("symbol")}",headers=headers); require(contract.getString("status")=="active" && contract.optBoolean("tradable",false) && contract.getString("size").toBigDecimal().compareTo(java.math.BigDecimal(100))==0) { "Only active standard 100-share option contracts are supported" } }
  val price = Policy.price(event.getString("limit_price"), config.optString("mode", "exact_limit"), sell, config.optInt("bps",100), config.optString("amount","0.02"))
  val body = JSONObject().put("symbol",event.getString("symbol")).put("qty",quantity.toString()).put("side",if(sell) "sell" else "buy").put("type",if(price==null) "market" else "limit").put("time_in_force","day").put("client_order_id",client)
  if (price != null) body.put("limit_price",price)
  if(event.getString("asset")=="option") body.put("position_intent",if(sell) "sell_to_close" else "buy_to_open")
  if(!canSubmit()) throw Superseded()
  return Network.request("$base/v2/orders", "POST", headers, body)
 }
}

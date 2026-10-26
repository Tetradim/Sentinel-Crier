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
class Broker(private val config: JSONObject, private val http:OAuthHttp=OAuthHttp { u,m,h,b -> Network.request(u,m,h,b) }): BrokerPort {
 init { require(config.optString("authMode")!="oauth" || config.optString("oauthPurpose")=="trade") { "Read-only Alerts consent cannot authorize trading" } }
 private fun request(url:String,method:String="GET",headers:Map<String,String> = emptyMap(),body:JSONObject?=null)=http.request(url,method,headers,body)
 private val base = if(config.getString("environment") == "paper") "https://paper-api.alpaca.markets" else "https://api.alpaca.markets"
 private val headers = BrokerAuth.headers(config)
 override fun account():String { val a=request("$base/v2/account", headers=headers); require(a.getString("status")=="ACTIVE" && !a.optBoolean("trading_blocked",true) && !a.optBoolean("account_blocked",true)) { "Broker account is not active for trading" }; return a.getString("id") }
 override fun order(client: String): JSONObject? = try { request("$base/v2/orders:by_client_order_id?client_order_id=$client", headers=headers) } catch(e: HttpError) { if(e.status == 404) null else throw e }
 override fun cancel(id: String) { try { request("$base/v2/orders/$id", "DELETE", headers) } catch(e: HttpError) { if(e.status !in setOf(404,422)) throw e } }
 override fun holdings(symbol: String): Int = try { request("$base/v2/positions/$symbol", headers=headers).optString("qty_available", "0").toBigDecimal().toInt().coerceAtLeast(0) } catch(e: HttpError) { if(e.status==404) 0 else throw e }
 override fun binding(event:JSONObject):JSONObject {
  val account=request("$base/v2/account",headers=headers)
  require(account.getString("id")==config.getString("account") && account.getString("status")=="ACTIVE" && !account.optBoolean("trading_blocked",true) && !account.optBoolean("account_blocked",true) && account.getString("currency")=="USD") { "USD active account metadata required" }
  val symbol=event.getString("symbol"); val asset=event.getString("asset")
  val instrument=request(if(asset=="option") "$base/v2/options/contracts/$symbol" else "$base/v2/assets/$symbol",headers=headers)
  require(instrument.getString("symbol")==symbol && instrument.getString("status")=="active" && instrument.optBoolean("tradable",false)) { "Instrument metadata unavailable" }
  require(!instrument.has("currency") || instrument.getString("currency")=="USD") { "Unsupported instrument currency" }
  val multiplier=if(asset=="option") { require(instrument.getString("size").toBigDecimal().compareTo(java.math.BigDecimal(100))==0) { "Standard option size required" }; 100 } else { require(asset=="stock" && instrument.getString("class")=="us_equity"); 1 }
  return JSONObject().put("account",account.getString("id")).put("environment",config.getString("environment")).put("symbol",symbol).put("asset",asset).put("currency","USD").put("multiplier",LivePolicy.multiplier(asset,multiplier))
 }
 override fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject {
  val fresh=try { binding(event) } catch(_:Exception) { throw Superseded() }
  val pinned=plan.getJSONObject("binding")
  if(listOf("account","environment","symbol","asset","currency","multiplier").any { fresh.get(it).toString()!=pinned.get(it).toString() }) throw Superseded()
  return post(event,client,quantity,sell,if(plan.isNull("price")) null else plan.getString("price"),canSubmit)
 }
 private fun post(event:JSONObject,client:String,quantity:Int,sell:Boolean,price:String?,canSubmit:()->Boolean):JSONObject {
  val body=JSONObject().put("symbol",event.getString("symbol")).put("qty",quantity.toString()).put("side",if(sell) "sell" else "buy").put("type",if(price==null) "market" else "limit").put("time_in_force","day").put("client_order_id",client)
  if(price!=null) body.put("limit_price",price)
  if(event.getString("asset")=="option") body.put("position_intent",if(sell) "sell_to_close" else "buy_to_open")
  if(!canSubmit()) throw Superseded()
  return request("$base/v2/orders","POST",headers,body)
 }
 override fun submit(event: JSONObject, client: String, quantity: Int, sell: Boolean, canSubmit:()->Boolean): JSONObject {
  if(event.getString("asset")=="option") { val contract=request("$base/v2/options/contracts/${event.getString("symbol")}",headers=headers); require(contract.getString("status")=="active" && contract.optBoolean("tradable",false) && contract.getString("size").toBigDecimal().compareTo(java.math.BigDecimal(100))==0) { "Only active standard 100-share option contracts are supported" } }
  val price = Policy.price(event.getString("limit_price"), config.optString("mode", "exact_limit"), sell, config.optInt("bps",100), config.optString("amount","0.02"))
  val body = JSONObject().put("symbol",event.getString("symbol")).put("qty",quantity.toString()).put("side",if(sell) "sell" else "buy").put("type",if(price==null) "market" else "limit").put("time_in_force","day").put("client_order_id",client)
  if (price != null) body.put("limit_price",price)
  if(event.getString("asset")=="option") body.put("position_intent",if(sell) "sell_to_close" else "buy_to_open")
  if(!canSubmit()) throw Superseded()
  return request("$base/v2/orders", "POST", headers, body)
 }
}

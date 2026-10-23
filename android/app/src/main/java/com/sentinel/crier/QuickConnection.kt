package com.sentinel.crier
import java.net.URI
import org.json.JSONObject
import org.json.JSONArray

object QuickConnection {
 fun defaultOrigin(context:android.content.Context):String = runCatching {
  val value=context.assets.open("connection-service.json").bufferedReader().use { JSONObject(it.readText()).optString("url") }
  if(value.isBlank()) "" else origin(value)
 }.getOrDefault("")
 data class Invitation(val origin:String,val code:String)
 fun origin(text:String):String {
  val u=URI(text.trim())
  require(u.scheme=="https" && !u.host.isNullOrBlank() && u.userInfo==null && u.query==null && u.fragment==null && u.path in listOf("","/") && (u.port==-1 || u.port in 1..65535)) { "Enter an HTTPS connection service origin without a path, query or credentials." }
  return u.toString().trimEnd('/')
 }
 fun code(text:String):String = text.uppercase(java.util.Locale.ROOT).filter { !it.isWhitespace() && it!='-' }.also { require(it.matches(Regex("[A-Z2-7]{16}"))) { "Enter a 16-character invitation code or complete invitation link." } }
 fun invitation(text:String,service:String):Invitation {
  if(!text.contains("://")) return Invitation(origin(service),code(text))
  val u=URI(text.trim()); require(u.path=="/connect" && u.query==null && u.fragment!=null) { "Invalid invitation link" }
  return Invitation(origin(URI(u.scheme,u.authority,"",null,null).toString()),code(u.fragment))
 }
 private fun credential(value:JSONObject,origin:String,role:String,environment:String):JSONObject {
  require(value.getString("role")==role && value.getString("environment")==environment && value.getString("token").isNotBlank()) { "Invitation environment or role differs. Select the matching environment." }
  return value.put("url",origin)
 }
 fun host(service:String,environment:String):JSONObject { val url=origin(service); return credential(Network.request("$url/api/connect/host","POST",body=JSONObject().put("name","Android").put("environment",environment)),url,"host",environment) }
 fun receive(invitation:Invitation,environment:String):JSONObject = credential(Network.request("${invitation.origin}/api/connect/receive","POST",body=JSONObject().put("code",invitation.code).put("environment",environment)),invitation.origin,"follower",environment)
 fun headers(pair:JSONObject)=mapOf("Authorization" to "Bearer ${pair.getString("token")}")
 fun invite(pair:JSONObject):String { val url=origin(pair.getString("url")); return "$url/connect#${code(Network.request("$url/api/connect/invite","POST",headers(pair)).getString("code"))}" }
 fun receivers(pair:JSONObject)=Network.requestValue("${origin(pair.getString("url"))}/api/connect/receivers",headers=headers(pair)) as JSONArray
 fun revoke(pair:JSONObject,id:String) { require(java.util.UUID.fromString(id).toString()==id); Network.request("${origin(pair.getString("url"))}/api/connect/receivers/$id/revoke","POST",headers(pair)) }
}

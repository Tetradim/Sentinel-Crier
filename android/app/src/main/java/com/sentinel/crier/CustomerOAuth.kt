package com.sentinel.crier

import org.json.JSONObject
import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID

/** Customer session custody is separate from both connection and Alerts documents. */
interface CustomerSessionStore { fun read():JSONObject; fun write(value:JSONObject) }
fun interface OAuthHttp { fun request(url:String,method:String,headers:Map<String,String>,body:JSONObject?):JSONObject }
object OAuthProvenance {
 fun valid(owner:String,service:String) { require(UUID.fromString(owner).toString()==owner) { "Customer identity unavailable" }; CustomerOAuth.trustedBase(service) }
 fun matches(c:JSONObject,owner:String,service:String,prefix:String="oauth"):Boolean = runCatching { valid(c.getString(prefix+"Owner"),c.getString(prefix+"Service")); c.getString(prefix+"Owner")==owner && c.getString(prefix+"Service")==service }.getOrDefault(false)
 fun requireDestination(c:JSONObject,customer:JSONObject,service:String) {
  if(c.has("discordOAuthOwner") || c.has("discordOAuthService")) require(customer.optString("service")==service && matches(c,customer.optString("owner"),service,"discordOAuth")) { "Sign in as the saved Discord customer before publishing" }
 }
 fun preserveDestination(old:JSONObject,next:JSONObject):JSONObject {
  if(old.optString("discordWebhook")==next.optString("discordWebhook")) {
   for(field in listOf("discordOAuthOwner","discordOAuthService","discordGuild","discordChannel")) {
    if(old.has(field)) next.put(field,old.get(field))
   }
  }
  return next
 }
}
object BrokerAuth {
 fun headers(c:JSONObject):Map<String,String> {
  if(c.optString("authMode")=="oauth") {
   OAuthProvenance.valid(c.optString("oauthOwner"),c.optString("oauthService"))
   require(c.optString("bearer").isNotBlank() && c.optString("oauthOwner").isNotBlank()) { "Sign in and reconnect your brokerage" }
   require(c.optString("key").isBlank() && c.optString("secret").isBlank()) { "Choose one brokerage authentication mode" }
   return mapOf("Authorization" to "Bearer ${c.getString("bearer")}")
  }
  require(c.optString("authMode") in setOf("","api_key") && c.optString("bearer").isBlank())
  require(c.optString("key").isNotBlank() && c.optString("secret").isNotBlank()) { "Enter your Alpaca credentials" }
  return mapOf("APCA-API-KEY-ID" to c.getString("key"),"APCA-API-SECRET-KEY" to c.getString("secret"))
 }
}

/** Serialized process-owned protocol. No automatic retries, including refresh and redemption. */
class CustomerOAuth(val base:String, private val sessions:CustomerSessionStore,
 private val http:OAuthHttp=OAuthHttp { u,m,h,b -> Network.request(u,m,h,b) },
 private val now:()->Long={ System.currentTimeMillis()/1000 },
 private val random:()->String={ ByteArray(32).also { SecureRandom().nextBytes(it) }.let { Base64.getUrlEncoder().withoutPadding().encodeToString(it) } },
 private val disconnected:()->Boolean={ true }) {
 companion object {
  fun trustedBase(value:String):String { require(value.matches(Regex("https://[a-z]{20}\\.supabase\\.co/functions/v1/crier-oauth"))) { "Use the trusted Supabase customer service" }; return value }
  fun sibling(relay:String):String = trustedBase(relay.removeSuffix("/functions/v1/crier")+"/functions/v1/crier-oauth")
 }
 init { trustedBase(base) }
 private data class Pending(val flow:String,val proof:String,val context:OAuthReturnContext,val receipt:PendingOAuthReturn)
 private var pending:Pending?=null
 private var available=emptySet<String>()
 @Synchronized fun owner():String=sessions.read().optString("owner")
 @Synchronized fun capabilities():Set<String> {
  available=emptySet()
  val c=http.request("$base/oauth/capabilities","GET",emptyMap(),null)
  require(c.getInt("version")==1 && c.getString("service_url")==base && c.getString("auth_project_url")==base.substringBefore("/functions/"))
  val a=c.getJSONArray("providers"); val names=(0 until a.length()).map { a.getString(it) }.toSet()
  require(names.all { it in setOf("alpaca","discord") }); available=names; return names
 }
 private fun validateSession(s:JSONObject):JSONObject {
  val id=s.getJSONObject("user").getString("id"); require(UUID.fromString(id).toString()==id)
  require(s.getString("token_type")=="bearer" && s.getString("access_token").isNotBlank() && s.getString("refresh_token").isNotBlank() && s.getLong("expires_in")>0)
  return JSONObject(s.toString()).put("owner",id).put("expiresAt",now()+s.getLong("expires_in")).put("service",base)
 }
 @Synchronized fun login(email:String,password:String,signup:Boolean=false):Boolean {
  require(available.isNotEmpty()) { "Check customer service availability first" }
  require(disconnected()) { "Stop all workers before customer sign in" }; require(owner().isBlank()) { "Sign out before changing customer" }; invalidate()
  val r=http.request("$base/auth/${if(signup) "signup" else "login"}","POST",emptyMap(),JSONObject().put("email",email).put("password",password))
  if(signup && r.isNull("session")) { require(r.getBoolean("requiresEmailConfirmation")); return false }
  sessions.write(validateSession(if(signup) r.getJSONObject("session") else r)); return true
 }
 @Synchronized fun refresh() {
  invalidate(); val old=sessions.read(); require(old.getString("service")==base)
  val updated=validateSession(http.request("$base/auth/refresh","POST",emptyMap(),JSONObject().put("refresh_token",old.getString("refresh_token"))))
  require(updated.getString("owner")==old.getString("owner")) { "Customer identity changed" }; sessions.write(updated)
 }
 private fun headers():Map<String,String> {
  val s=sessions.read(); require(s.getString("service")==base && s.getLong("expiresAt")>now()) { "Refresh your customer session explicitly" }
  return mapOf("Authorization" to "Bearer ${s.getString("access_token")}")
 }
 @Synchronized fun begin(provider:String,purpose:String,environment:String):String {
  require(provider in available) { "Provider unavailable; check service capabilities" }; require(pending==null) { "Cancel the current authorization first" }
  val context=OAuthReturnContext(owner(),provider,environment,purpose); val proof=random(); require(OAuthReturn.validFlow(proof))
  val challenge=MessageDigest.getInstance("SHA-256").digest(proof.toByteArray(Charsets.US_ASCII)).joinToString("") { "%02x".format(it) }
  val r=http.request("$base/oauth/begin","POST",headers(),JSONObject().put("provider",provider).put("purpose",purpose).put("environment",environment).put("challenge",challenge))
  val flow=r.getString("flow"); val expiry=r.getLong("expires_at"); require(OAuthReturn.validFlow(flow) && expiry>now() && expiry<=now()+300)
  val launch=r.getString("launch_url"); val u=URI(launch)
  require(launch.startsWith("$base/oauth/browser?ticket=") && u.fragment==null && u.userInfo==null && u.rawQuery.matches(Regex("ticket=[A-Za-z0-9_-]{43}")))
  pending=Pending(flow,proof,context,PendingOAuthReturn(flow,context,expiry.toDouble())); return launch
 }
 @Synchronized fun complete(raw:String):JSONObject {
  val p=pending ?: error("No authorization pending in this app process; begin again")
  require(p.context.owner==owner()) { "Customer changed" }
  require(OAuthReturn.matchPending(p.receipt,raw,p.flow,p.context,now().toDouble())!=null) { "Unrecognized or expired authorization return" }
  pending=null // Never retry a consumed notification or one-use redemption after an ambiguous response.
  val h=headers(); val status=http.request("$base/oauth/status","POST",h,JSONObject().put("flow",p.flow))
  require(status.getString("stage")=="ready") { "Authorization is not ready; begin again" }
  val grant=http.request("$base/oauth/redeem","POST",h,JSONObject().put("flow",p.flow).put("proof",p.proof))
  require(grant.getString("provider")==p.context.provider && grant.getString("purpose")==p.context.purpose && grant.getString("environment")==p.context.environment)
  require(grant.getString("credential").isNotBlank()); val scopes=grant.getJSONArray("scopes"); val allowed=if(p.context.provider=="discord") setOf("webhook.incoming") else if(p.context.purpose=="trade") setOf("trading") else emptySet()
  val scopeNames=(0 until scopes.length()).map { scopes.getString(it) }; require(scopeNames.toSet()==allowed && scopeNames.size==allowed.size)
  if(p.context.provider=="alpaca") require(UUID.fromString(grant.getString("account_id")).toString()==grant.getString("account_id"))
  else { Discord.destination(grant.getString("credential")); require(grant.getString("guild_id").matches(Regex("[0-9]+")) && grant.getString("channel_id").matches(Regex("[0-9]+"))) }
  return grant.put("oauthOwner",p.context.owner).put("oauthService",base)
 }
 @Synchronized fun cancel() { val p=pending ?: return; pending=null; p.receipt.invalidate(); http.request("$base/oauth/cancel","POST",headers(),JSONObject().put("flow",p.flow).put("proof",p.proof)) }
 @Synchronized fun invalidate() { pending?.receipt?.invalidate(); pending=null }
 @Synchronized fun logout() { require(disconnected()) { "Stop all workers before signing out" }; invalidate(); sessions.write(JSONObject()) }
}

object OAuthInstall {
 fun broker(old:JSONObject,grant:JSONObject,owner:String,stopped:Boolean,createProfile:Boolean=false,account:(JSONObject)->String):JSONObject {
  OAuthProvenance.valid(owner,grant.getString("oauthService"))
  require(stopped && grant.getString("provider")=="alpaca" && grant.getString("oauthOwner")==owner)
  require(old.optString("environment",grant.getString("environment"))==grant.getString("environment")) { "Environment changes need a separate connection" }
  if(old.optString("authMode")=="oauth" || old.has("oauthOwner") || old.has("oauthService")) require(OAuthProvenance.matches(old,owner,grant.getString("oauthService"))) { "Saved connection belongs to another customer service" }
  if(old.has("discordOAuthOwner") || old.has("discordOAuthService")) require(OAuthProvenance.matches(old,owner,grant.getString("oauthService"),"discordOAuth")) { "Saved destination belongs to another customer service" }
  require(createProfile || !old.has("account") || old.getString("account")==grant.getString("account_id")) { "Use a separate saved account journal" }
  val c=JSONObject(old.toString()).put("environment",grant.getString("environment")).put("authMode","oauth").put("bearer",grant.getString("credential")).put("oauthOwner",owner).put("oauthService",grant.getString("oauthService")).put("oauthPurpose",grant.getString("purpose"))
  c.remove("key"); c.remove("secret")
  require(account(c)==grant.getString("account_id")) { "Redeemed broker identity differs" }; return c.put("account",grant.getString("account_id"))
 }
 fun forget(c:JSONObject) { if(c.optString("authMode")=="oauth") c.remove("bearer"); if(c.optString("discordOAuthOwner").isNotBlank()) c.remove("discordWebhook") }
}

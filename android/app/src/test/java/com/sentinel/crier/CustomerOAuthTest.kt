package com.sentinel.crier

import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*

class CustomerOAuthTest {
 private val base="https://abcdefghijklmnopqrst.supabase.co/functions/v1/crier-oauth"
 private val owner="11111111-1111-4111-8111-111111111111"
 private val account="22222222-2222-4222-8222-222222222222"
 private val flow="F".repeat(43)
 private class Memory:CustomerSessionStore { var value=JSONObject(); override fun read()=JSONObject(value.toString()); override fun write(value:JSONObject) { this.value=JSONObject(value.toString()) } }
 private fun session(id:String=owner)=JSONObject().put("access_token","customer-access").put("refresh_token","customer-refresh").put("expires_in",600).put("token_type","bearer").put("user",JSONObject().put("id",id))
 private fun grant()=JSONObject().put("provider","alpaca").put("purpose","trade").put("environment","paper").put("account_id",account).put("credential","provider-bearer").put("oauthService",base).put("scopes",JSONArray().put("trading"))
 private fun rejected(block:()->Unit) { try { block(); fail("Expected refusal") } catch(_:IllegalArgumentException) {} catch(_:IllegalStateException) {} }
 @Test fun loginConsentRedeemInstallRestartLogout() {
  val memory=Memory(); val requests=mutableListOf<String>(); var proof=""
  val transport=OAuthHttp { url,method,headers,body ->
   val path=url.removePrefix(base); requests.add(path)
   when(path) {
    "/oauth/capabilities" -> { assertEquals("GET",method); JSONObject().put("version",1).put("service_url",base).put("auth_project_url",base.substringBefore("/functions/")).put("providers",JSONArray().put("alpaca")) }
    "/auth/login" -> { assertTrue(headers.isEmpty()); session() }
    "/oauth/begin" -> { assertEquals("Bearer customer-access",headers["Authorization"]); assertEquals(64,body!!.getString("challenge").length); JSONObject().put("flow",flow).put("expires_at",200).put("launch_url","$base/oauth/browser?ticket=${"T".repeat(43)}") }
    "/oauth/status" -> JSONObject().put("stage","ready")
    "/oauth/redeem" -> { proof=body!!.getString("proof"); grant() }
    else -> error("Unexpected request")
   }
  }
  val client=CustomerOAuth(base,memory,transport,{100},{"P".repeat(43)})
  rejected { client.begin("alpaca","trade","paper") }; client.capabilities(); assertTrue(client.login("customer@example.test","password"))
  client.begin("alpaca","trade","paper")
  rejected { client.complete("sentinelcrier://oauth/complete?flow=${"X".repeat(43)}") }
  assertEquals(3,requests.size)
  val result=client.complete("sentinelcrier://oauth/complete?flow=$flow"); assertEquals("P".repeat(43),proof)
  val old=JSONObject().put("account",account).put("environment","paper").put("token","relay-owner").put("role","host").put("url","https://relay.example")
  val installed=OAuthInstall.broker(old,result,owner,true) { c -> assertEquals(mapOf("Authorization" to "Bearer provider-bearer"),BrokerAuth.headers(c)); account }
  assertEquals(account,installed.getString("account")); assertEquals("relay-owner",installed.getString("token"))
  rejected { client.complete("sentinelcrier://oauth/complete?flow=$flow") }
  val restarted=CustomerOAuth(base,memory,transport,{100}); assertEquals(owner,restarted.owner()); rejected { restarted.complete("sentinelcrier://oauth/complete?flow=$flow") }
  OAuthInstall.forget(installed); restarted.logout(); assertEquals("",restarted.owner()); assertFalse(installed.has("bearer")); assertEquals(account,installed.getString("account")); rejected { BrokerAuth.headers(installed) }
 }
 @Test fun installRejectsActiveWrongOwnerEnvironmentAccountAndIdentity() {
  val g=grant().put("oauthOwner",owner); val old=JSONObject().put("account",account).put("environment","paper")
  rejected { OAuthInstall.broker(old,g,owner,false) { account } }
  rejected { OAuthInstall.broker(old,g,"other",true) { account } }
  rejected { OAuthInstall.broker(JSONObject(old.toString()).put("environment","live"),g,owner,true) { account } }
  rejected { OAuthInstall.broker(JSONObject(old.toString()).put("account",owner),g,owner,true) { account } }
  rejected { OAuthInstall.broker(old,g,owner,true) { owner } }
  rejected { OAuthInstall.broker(JSONObject(old.toString()).put("oauthOwner","other"),g,owner,true,true) { account } }
 }
 @Test fun authenticationModeNeverMixesHeadersAndTrustIsExact() {
  rejected { CustomerOAuth.trustedBase(base+"/") }; rejected { CustomerOAuth.trustedBase(base.replace(".supabase.co",".supabase.co.evil")) }
  assertEquals(base,CustomerOAuth.sibling(base.replace("crier-oauth","crier")))
  val keys=JSONObject().put("key","key").put("secret","secret"); assertFalse(BrokerAuth.headers(keys).containsKey("Authorization"))
  rejected { BrokerAuth.headers(keys.put("authMode","oauth").put("bearer","token").put("oauthOwner",owner)) }
 }
 @Test fun ambiguousRedemptionConsumesReceiptAndExplicitRefreshPinsOwner() {
  val memory=Memory(); memory.write(session().put("owner",owner).put("service",base).put("expiresAt",700))
  var redeems=0
  val client=CustomerOAuth(base,memory,OAuthHttp { url,_,_,_ -> when(url.removePrefix(base)) {
   "/oauth/capabilities" -> JSONObject().put("version",1).put("service_url",base).put("auth_project_url",base.substringBefore("/functions/")).put("providers",JSONArray().put("alpaca"))
   "/oauth/begin" -> JSONObject().put("flow",flow).put("expires_at",200).put("launch_url","$base/oauth/browser?ticket=${"T".repeat(43)}")
   "/oauth/status" -> JSONObject().put("stage","ready")
   "/oauth/redeem" -> { redeems++; error("lost acknowledgement") }
   "/auth/refresh" -> session(account)
   else -> error("Unexpected")
  } },{100},{"P".repeat(43)})
  client.capabilities(); client.begin("alpaca","trade","paper")
  repeat(2) { rejected { client.complete("sentinelcrier://oauth/complete?flow=$flow") } }; assertEquals(1,redeems)
  rejected { client.refresh() }; assertEquals(owner,client.owner())
 }
 @Test fun brokerAdapterUsesBearerAndRejectsReadOnlyConsent() {
  val c=JSONObject().put("environment","paper").put("account",account).put("authMode","oauth").put("oauthOwner",owner).put("oauthService",base).put("oauthPurpose","trade").put("bearer","provider-token")
  var reads=0
  val broker=Broker(c,OAuthHttp { url,method,headers,body -> reads++; assertEquals("https://paper-api.alpaca.markets/v2/account",url); assertEquals("GET",method); assertNull(body); assertEquals(mapOf("Authorization" to "Bearer provider-token"),headers); JSONObject().put("id",account).put("status","ACTIVE").put("trading_blocked",false).put("account_blocked",false) })
  assertEquals(account,broker.account()); assertEquals(1,reads)
  rejected { Broker(JSONObject(c.toString()).put("oauthPurpose","alerts")) }
 }
 @Test fun alertsInstallRestartDestinationGuardAndLogoutRetainUncertainEvidence() {
  val d=object:AlertsDocument { var text="{}"; override fun read()=JSONObject(text); override fun write(value:JSONObject) { text=value.toString() }; override fun customer()=JSONObject().put("owner",owner).put("service",base) }
  val r=object:FillReadPort { override fun account()=account; override fun fills(after:String,page:String?)=JSONArray() }
  val g=GuidedAlerts(d,{r},{_,_-> error("lost acknowledgement") })
  val config=OAuthInstall.broker(JSONObject(),grant().put("purpose","alerts").put("scopes",JSONArray()).put("oauthOwner",owner),owner,true) { account }
   .put("discordWebhook","https://discord.com/api/webhooks/123/abc").put("discordOAuthOwner",owner).put("discordOAuthService",base)
  g.verify(config); assertFalse(g.isEnabled()); g.preview(); g.test(); assertTrue(g.history().contains("uncertain")); g.stop()
  rejected { g.verify(JSONObject(config.toString()).put("discordWebhook","https://discord.com/api/webhooks/456/def")) }
  val reopened=GuidedAlerts(d,{r}); assertFalse(reopened.isEnabled()); rejected { reopened.enable() }
  reopened.forgetOAuth(); val saved=reopened.saved(); assertEquals(account,saved.getString("account")); assertFalse(saved.has("bearer")); assertFalse(saved.has("discordWebhook")); assertTrue(reopened.history().contains("uncertain"))
 } @Test fun exactServiceProvenanceFencesSameUuidAcrossProjectsAndMissingMetadata() {
  val other="https://zyxwvutsrqponmlkjihg.supabase.co/functions/v1/crier-oauth"
  val g=grant().put("oauthOwner",owner)
  val old=JSONObject().put("authMode","oauth").put("oauthOwner",owner).put("oauthService",other).put("account",account).put("environment","paper").put("bearer","old")
  assertFalse(OAuthProvenance.matches(old,owner,base))
  rejected { OAuthInstall.broker(old,g,owner,true) { account } }
  old.remove("oauthService"); rejected { BrokerAuth.headers(old) }; rejected { OAuthInstall.broker(old,g,owner,true) { account } }
  old.put("oauthService",base); assertTrue(OAuthProvenance.matches(old,owner,base)); assertEquals(account,OAuthInstall.broker(old,g,owner,true) { account }.getString("account"))
  val inherited=JSONObject(old.toString()).put("discordOAuthOwner",owner).put("discordOAuthService",other); rejected { OAuthInstall.broker(inherited,g,owner,true) { account } }
  val discord=JSONObject().put("discordOAuthOwner",owner).put("discordOAuthService",other)
  assertFalse(OAuthProvenance.matches(discord,owner,base,"discordOAuth")); discord.remove("discordOAuthService"); assertFalse(OAuthProvenance.matches(discord,owner,base,"discordOAuth"))
 }
 @Test fun ordinaryDestinationSaveCannotStripOAuthProvenance() {
  val old=JSONObject().put("discordWebhook","same").put("discordOAuthOwner",owner).put("discordOAuthService",base)
  val next=OAuthProvenance.preserveDestination(old,JSONObject().put("discordWebhook","same").put("key","manual"))
  assertTrue(OAuthProvenance.matches(next,owner,base,"discordOAuth"))
  old.remove("discordOAuthService")
  val incomplete=OAuthProvenance.preserveDestination(old,JSONObject().put("discordWebhook","same"))
  assertTrue(incomplete.has("discordOAuthOwner")); assertFalse(OAuthProvenance.matches(incomplete,owner,base,"discordOAuth"))
  assertFalse(OAuthProvenance.preserveDestination(old,JSONObject().put("discordWebhook","different")).has("discordOAuthOwner"))
 }
 @Test fun destinationOwnershipIsCheckedBeforeSendingIndependentlyOfManualBrokerKeys() {
  val c=JSONObject().put("key","manual").put("discordOAuthOwner",owner).put("discordOAuthService",base)
  rejected { OAuthProvenance.requireDestination(c,JSONObject(),base) }
  val identity=JSONObject().put("owner",owner).put("service",base)
  OAuthProvenance.requireDestination(c,identity,base)
  rejected { OAuthProvenance.requireDestination(c,identity,base.replace("abcdefghijklmnopqrst","zyxwvutsrqponmlkjihg")) }
  OAuthProvenance.requireDestination(JSONObject().put("key","manual"),JSONObject(),base)
 }
 @Test fun inactiveReturnWaitsWithoutConsumingAndProcessRestartHasNoInbox() {
  val inbox=OAuthReturnInbox(); val raw="sentinelcrier://oauth/complete?flow=$flow"
  inbox.enqueue(raw); assertNull(inbox.take(false)); assertNull(inbox.take(false)); assertEquals(raw,inbox.take(true)); assertNull(inbox.take(true))
  inbox.enqueue(raw+"&token=bad"); assertNull(inbox.take(true)); inbox.enqueue(raw); inbox.clear(); assertNull(inbox.take(true)); assertNull(OAuthReturnInbox().take(true))
 }
 @Test fun workersFenceLoginAndLogoutAndFailedRefreshKeepsOriginalSessionOwner() {
  val memory=Memory(); var running=true; var calls=0
  val client=CustomerOAuth(base,memory,OAuthHttp { url,_,_,_ -> calls++; if(url.endsWith("capabilities")) JSONObject().put("version",1).put("service_url",base).put("auth_project_url",base.substringBefore("/functions/")).put("providers",JSONArray().put("alpaca")) else error("refresh failed") },{100},disconnected={ !running })
  client.capabilities(); rejected { client.login("new@example.test","password") }; assertEquals(1,calls)
  memory.write(session().put("owner",owner).put("service",base).put("expiresAt",700))
  rejected { client.refresh() }; assertEquals(owner,client.owner()); rejected { client.login("new@example.test","password") }; rejected { client.logout() }; assertEquals(owner,client.owner())
  running=false; rejected { client.login("new@example.test","password") }; client.logout(); assertEquals("",client.owner())
 }}

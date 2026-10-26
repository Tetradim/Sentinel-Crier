package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
class BrokerLifecycleFenceTest {
 private val service="https://abcdefghijklmnopqrst.supabase.co/functions/v1/crier-oauth"
 private val owner="11111111-1111-4111-8111-111111111111"
 private fun config()=JSONObject().put("account","account").put("environment","paper").put("role","follower").put("url","https://relay.example").put("token","pairing").put("authMode","oauth").put("bearer","test-bearer").put("oauthOwner",owner).put("oauthService",service).put("oauthPurpose","trade")
 @Test fun finalCancelRefusesStoppedInterruptedLoggedOutOrChangedOwnerBeforeDelete() {
  for(fault in listOf("stop","interrupt","logout","owner","credential","profile")) {
   try {
    val c=config(); var saved=JSONObject(c.toString()); var customer=JSONObject().put("owner",owner).put("service",service); var active=true; var deletes=0
    val fence=BrokerLifecycleFence(c,{active},{saved},{customer},service)
    val raw=Broker(c,OAuthHttp { _,method,_,_ -> assertEquals("DELETE",method); deletes++; JSONObject() })
    val observed=object:BrokerPort by raw { override fun cancel(id:String) { fence.check(); raw.cancel(id) } }
    when(fault) { "stop"->active=false; "interrupt"->Thread.currentThread().interrupt(); "logout"->customer=JSONObject(); "owner"->customer.put("owner","22222222-2222-4222-8222-222222222222"); "credential"->saved.remove("bearer"); "profile"->saved.put("account","changed") }
    if(fault=="interrupt") { assertThrows(InterruptedException::class.java) { observed.cancel("bound-broker-id") }; assertTrue(Thread.currentThread().isInterrupted) }
    else assertThrows(Superseded::class.java) { observed.cancel("bound-broker-id") }
    assertEquals(fault,0,deletes)
   } finally { Thread.interrupted() }
  }
 }
 @Test fun pausedEntriesStillPermitAnActiveOwnersBoundCancellation() {
  val c=config().put("paused",true); val session=JSONObject().put("owner",owner).put("service",service); var deletes=0
  val fence=BrokerLifecycleFence(c,{true},{JSONObject(c.toString())},{session},service)
  val raw=Broker(c,OAuthHttp { url,method,_,_ -> assertTrue(url.endsWith("/orders/bound-broker-id")); assertEquals("DELETE",method); deletes++; JSONObject() })
  fence.check(); raw.cancel("bound-broker-id"); assertEquals(1,deletes)
 }
 @Test fun apiKeyRotationAlsoRevokesTheOldCancellationCredentials() {
  val c=config().apply { remove("bearer"); put("authMode","api_key"); put("key","fake-key"); put("secret","fake-secret") }; val saved=JSONObject(c.toString())
  val fence=BrokerLifecycleFence(c,{true},{saved},{JSONObject()},service); saved.put("secret","rotated-secret")
  assertThrows(Superseded::class.java) { fence.check() }
 }
}

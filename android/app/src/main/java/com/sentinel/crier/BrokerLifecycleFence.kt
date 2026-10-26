package com.sentinel.crier
import org.json.JSONObject

/** Rechecked at the final mutation boundary; pausing entries does not revoke cancellations. */
class BrokerLifecycleFence(config:JSONObject,private val active:()->Boolean,private val saved:()->JSONObject,private val customer:()->JSONObject,private val service:String) {
 private val original=JSONObject(config.toString())
 private val headers=BrokerAuth.headers(original)
 fun check() {
  interrupted()
  if(!active()) throw Superseded()
  try {
   val current=saved()
   require(Settings.sameIdentity(original,current) && BrokerAuth.headers(current)==headers)
   if(original.optString("authMode")=="oauth") {
    val session=customer()
    require(current.optString("oauthPurpose")=="trade" && session.optString("service")==service && OAuthProvenance.matches(original,session.optString("owner"),service) && OAuthProvenance.matches(current,session.optString("owner"),service))
   }
  } catch(error:Exception) {
   if(error is InterruptedException) { Thread.currentThread().interrupt(); throw error }
   if(error is java.util.concurrent.CancellationException || error is Superseded) throw error
   throw Superseded()
  }
  interrupted()
  if(!active()) throw Superseded()
 }
 companion object {
  fun interrupted() { if(Thread.currentThread().isInterrupted) throw InterruptedException("Execution worker interrupted") }
 }
}

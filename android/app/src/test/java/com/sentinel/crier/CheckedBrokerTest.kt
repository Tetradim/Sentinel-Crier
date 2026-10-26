package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
class CheckedBrokerTest {
 private fun config()=JSONObject().put("account","account").put("environment","paper").put("role","follower").put("key","fake-key").put("secret","fake-secret")
 private fun event(asset:String="stock")=JSONObject().put("asset",asset).put("symbol",if(asset=="option") "SPY261023C00500000" else "SPY").put("limit_price","1")
 @Test fun adapterRevalidatesAccountCurrencyAndMetadataBeforeFinalCallbackAndNeverLeaksPlan() {
  var currency="USD"; var assetClass="us_equity"; var posts=0; var callbacks=0
  val transport=OAuthHttp { url,method,_,body -> when {
   url.endsWith("/account")->JSONObject().put("id","account").put("status","ACTIVE").put("currency",currency).put("trading_blocked",false).put("account_blocked",false)
   url.contains("/assets/")->JSONObject().put("symbol","SPY").put("class",assetClass).put("status","active").put("tradable",true)
   method=="POST"->{ posts++; assertEquals(setOf("symbol","qty","side","type","time_in_force","client_order_id","limit_price"),body!!.keys().asSequence().toSet()); assertEquals("1.23",body.getString("limit_price")); JSONObject() }
   else->error("Unexpected HTTP")
  } }
  val broker=Broker(config(),transport); val e=event(); val plan=JSONObject().put("binding",broker.binding(e)).put("price","1.23")
  currency="EUR"; assertThrows(Superseded::class.java) { broker.submitPlanned(e,"client",3,false,plan) { callbacks++; true } }; assertEquals(0,callbacks); assertEquals(0,posts)
  currency="USD"; assetClass="crypto"; assertThrows(Superseded::class.java) { broker.submitPlanned(e,"client",3,false,plan) { true } }; assertEquals(0,posts)
  assetClass="us_equity"; assertThrows(Superseded::class.java) { broker.submitPlanned(e,"client",3,false,plan) { false } }; assertEquals(0,posts)
  broker.submitPlanned(e,"client",3,false,plan) { true }; assertEquals(1,posts)
 }
 @Test fun onlyVerifiedStandardOptionsHaveMultiplierOneHundred() {
  var size="100.0"; var currency:String?=null
  val broker=Broker(config(),OAuthHttp { url,_,_,_ -> if(url.endsWith("/account")) JSONObject().put("id","account").put("status","ACTIVE").put("currency","USD").put("trading_blocked",false).put("account_blocked",false) else JSONObject().put("symbol",event("option").getString("symbol")).put("status","active").put("tradable",true).put("size",size).also { if(currency!=null) it.put("currency",currency) } })
  assertEquals(100,broker.binding(event("option")).getInt("multiplier")); size="50"
  assertThrows(IllegalArgumentException::class.java) { broker.binding(event("option")) }; size="100"; currency="CAD"
  assertThrows(IllegalArgumentException::class.java) { broker.binding(event("option")) }
 }
 @Test fun unsupportedCheckedPortRefusesInsteadOfCallingUncheckedSubmit() {
  val fake=EngineTest.Fake(); val port=object:BrokerPort by fake {}
  assertThrows(Superseded::class.java) { port.submitPlanned(event(),"client",1,false,JSONObject()) { true } }; assertEquals(0,fake.posts)
 }
}

package com.sentinel.crier
import android.content.Context
import android.content.ContextWrapper
import org.json.JSONObject
interface RouteOwner { val routeId:String }
class RouteContext(context:Context,override val routeId:String):ContextWrapper(context),RouteOwner {
 override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences(RouteStorage.preferences(name,routeId),mode)
}
object RouteStorage {
 @Synchronized fun sharedFeatureRoute(context:Context):String {
  val prefs=context.applicationContext.getSharedPreferences("shared-feature-route",Context.MODE_PRIVATE)
  prefs.getString("id",null)?.let { return it }
  val profiles=Vault(context.applicationContext).profiles()
  val id=profiles.firstOrNull { it.getString("id")=="legacy" }?.getString("id") ?: profiles.firstOrNull()?.getString("id") ?: return "legacy"
  check(prefs.edit().putString("id",id).commit()); return id
 }

 fun id(context:Context):String=(context as? RouteOwner)?.routeId ?: Vault(context).profiles().let { profiles -> profiles.firstOrNull { it.getJSONObject("config").optString("profile","legacy")==Vault(context).read().optString("profile","legacy") }?.getString("id") ?: "legacy" }
 fun preferences(name:String,id:String):String { require(id=="legacy" || java.util.UUID.fromString(id).toString()==id); return if(name in setOf("controls","journey","component-health") && id!="legacy") "$name-$id" else name }
 fun accountKey(config:JSONObject):String = RouteAccounts.key(config)
}
object RouteAccounts {
 fun requireAvailable(id:String,config:JSONObject,profiles:List<Pair<String,JSONObject>>) { val account=key(config); require(profiles.none { (owner,saved) -> owner!=id && saved.has("account") && key(saved)==account }) { "Account already owns retained execution history in another route. Select that route to recover it." } }
 fun key(config:JSONObject):String { val broker=config.optString("broker","alpaca").lowercase(); require(broker=="alpaca") { "Only Alpaca execution is supported" }; val account=config.getString("account").trim(); require(account.isNotBlank()); val env=config.getString("environment"); require(env in setOf("paper","live")); return "$broker:$env:$account" }
}

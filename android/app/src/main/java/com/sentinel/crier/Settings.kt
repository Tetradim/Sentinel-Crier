package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONArray
import java.util.UUID

/** Versioned encrypted settings. Legacy settings keep intent.db and all ownership evidence. */
object Settings {
 fun migrate(raw:JSONObject):JSONObject {
  if(raw.optInt("schema")==2) return raw
  require(!raw.has("schema") || raw.optInt("schema") in 0..1) { "Settings were written by a newer app version. Keep the encrypted vault and update Crier." }
  val profiles=JSONArray()
  if(raw.length()>0) profiles.put(JSONObject().put("id","legacy").put("config",raw))
  return JSONObject().put("schema",2).put("active",if(profiles.length()>0) "legacy" else "").put("profiles",profiles)
 }
 fun active(root:JSONObject):JSONObject { val p=root.getJSONArray("profiles"); for(i in 0 until p.length()) if(p.getJSONObject(i).getString("id")==root.optString("active")) return p.getJSONObject(i).getJSONObject("config"); return JSONObject() }
 fun journalName(config:JSONObject):String { val id=config.optString("profile","legacy"); require(id=="legacy" || UUID.fromString(id).toString()==id); return if(id=="legacy") "intent.db" else "intent-$id.db" }
 fun sameIdentity(a:JSONObject,b:JSONObject)=listOf("account","environment","role","url","token").all { a.optString(it)==b.optString(it) }
 fun save(root:JSONObject,config:JSONObject,newProfile:Boolean=false) {
  val profiles=root.getJSONArray("profiles"); val current=active(root)
  if(current.has("account") && !newProfile) require(sameIdentity(current,config)) { "Choose a separate saved connection to change account or channel. Existing execution history will be retained." }
  val id=if(newProfile || root.optString("active").isBlank()) UUID.randomUUID().toString() else root.getString("active")
  config.put("profile",id)
  for(i in 0 until profiles.length()) if(profiles.getJSONObject(i).getString("id")==id) { profiles.getJSONObject(i).put("config",config); root.put("active",id); return }
  profiles.put(JSONObject().put("id",id).put("config",config)); root.put("active",id)
 }
}

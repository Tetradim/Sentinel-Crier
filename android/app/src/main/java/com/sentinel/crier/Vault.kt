package com.sentinel.crier
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import java.security.KeyStore
import org.json.JSONObject
class Vault(private val context: Context, private val namespace:String="vault") {
 private val prefs = context.getSharedPreferences(namespace, Context.MODE_PRIVATE)
 private fun alias()=if(namespace=="vault") "crier" else "crier-$namespace"
 private fun key(): SecretKey {
  val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
  if (!ks.containsAlias(alias())) KeyGenerator.getInstance("AES", "AndroidKeyStore").apply { init(KeyGenParameterSpec.Builder(alias(), KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes("GCM").setEncryptionPaddings("NoPadding").build()); generateKey() }
  return ks.getKey(alias(), null) as SecretKey
 }
 private fun writeRoot(value: JSONObject) {
  val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
  val encrypted = cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8))
  check(prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
 }
 @Synchronized fun readDocument(): JSONObject = synchronized(Vault::class.java) {
  val data = prefs.getString("data", null) ?: return@synchronized JSONObject()
  val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP))) }
  JSONObject(String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP)), Charsets.UTF_8))
 }
 @Synchronized fun writeDocument(value:JSONObject)=synchronized(Vault::class.java) { writeRoot(value) }
 private fun root()=Settings.migrate(readDocument()).also { root ->
  val rows=root.getJSONArray("profiles"); require(rows.length()<=16) { "Too many retained routes; manual recovery required (maximum 16)" }; val ids=mutableSetOf<String>(); val accounts=mutableSetOf<String>()
  for(i in 0 until rows.length()) { val row=rows.getJSONObject(i); val id=row.getString("id"); RouteStorage.preferences("controls",id); require(ids.add(id)) { "Duplicate route identity; retained storage requires recovery" }; val config=row.getJSONObject("config"); if(config.has("account")) require(accounts.add(RouteAccounts.key(config))) { "Multiple retained routes claim the same broker account; recovery required" }; require(config.optString("profile","legacy")==id) { "Route journal identity mismatch; retained storage requires recovery" } }
  (context as? RouteOwner)?.let { require(rows.length()==0 || it.routeId in ids) { "Selected route is unavailable; retained storage requires recovery" }; root.put("active",it.routeId) }
 }
 @Synchronized fun read():JSONObject = Settings.active(root())
 @Synchronized fun save(value:JSONObject,newProfile:Boolean=false) = synchronized(Vault::class.java) { val r=root(); require(!newProfile || r.getJSONArray("profiles").length()<16) { "Maximum 16 routes; all existing journals remain retained" }; val previous=Settings.active(r); LivePolicy.selected(value); if(LivePolicy.selection(previous)!=LivePolicy.selection(value)) { require(!SyncService.active(context)) { "Stop workers before changing follower policy" }; check(context.getSharedPreferences("controls",Context.MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()) }; if(value.has("account")) {
   val owner=if(newProfile) "" else r.optString("active")
   RouteAccounts.requireAvailable(owner,value,(0 until r.getJSONArray("profiles").length()).map { val row=r.getJSONArray("profiles").getJSONObject(it); row.getString("id") to row.getJSONObject("config") })
  }; Settings.save(r,value,newProfile); writeRoot(r) }
 @Synchronized fun profiles():List<JSONObject> { val p=root().getJSONArray("profiles"); return (0 until p.length()).map { p.getJSONObject(it) } }
 @Synchronized fun forgetOAuthCredentials() = synchronized(Vault::class.java) { val r=root(); val profiles=r.getJSONArray("profiles"); for(i in 0 until profiles.length()) OAuthInstall.forget(profiles.getJSONObject(i).getJSONObject("config")); writeRoot(r) }
 @Synchronized fun select(id:String) = synchronized(Vault::class.java) { val r=root(); require(profiles().any { it.getString("id")==id }); r.put("active",id); writeRoot(r) }
}

class EncryptedAlertsDocument(context:Context):AlertsDocument {
 private val vault=Vault(context,"alerts-only")
 private val sessions=EncryptedCustomerSessions(context)
 private val service=runCatching { CustomerOAuth.sibling(QuickConnection.defaultOrigin(context)) }.getOrDefault("")
 override fun read()=vault.readDocument()
 override fun write(value:JSONObject)=vault.writeDocument(value)
 override fun customer()=sessions.read().takeIf { it.optString("service")==service } ?: JSONObject()
}

class EncryptedCustomerSessions(context:Context):CustomerSessionStore {
 private val vault=Vault(context,"customer-session")
 override fun read()=vault.readDocument()
 override fun write(value:JSONObject)=vault.writeDocument(value)
}

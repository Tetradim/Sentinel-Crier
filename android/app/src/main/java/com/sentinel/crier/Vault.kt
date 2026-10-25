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
class Vault(context: Context, private val namespace:String="vault") {
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
 @Synchronized fun readDocument(): JSONObject {
  val data = prefs.getString("data", null) ?: return JSONObject()
  val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP))) }
  return JSONObject(String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP)), Charsets.UTF_8))
 }
 @Synchronized fun writeDocument(value:JSONObject)=writeRoot(value)
 private fun root()=Settings.migrate(readDocument())
 @Synchronized fun read():JSONObject = Settings.active(root())
 @Synchronized fun save(value:JSONObject,newProfile:Boolean=false) { val r=root(); Settings.save(r,value,newProfile); writeRoot(r) }
 @Synchronized fun profiles():List<JSONObject> { val p=root().getJSONArray("profiles"); return (0 until p.length()).map { p.getJSONObject(it) } }
 @Synchronized fun forgetOAuthCredentials() { val r=root(); val profiles=r.getJSONArray("profiles"); for(i in 0 until profiles.length()) OAuthInstall.forget(profiles.getJSONObject(i).getJSONObject("config")); writeRoot(r) }
 @Synchronized fun select(id:String) { val r=root(); require(profiles().any { it.getString("id")==id }); r.put("active",id); writeRoot(r) }
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

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
class Vault(context: Context) {
 private val prefs = context.getSharedPreferences("vault", Context.MODE_PRIVATE)
 private fun key(): SecretKey {
  val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
  if (!ks.containsAlias("crier")) KeyGenerator.getInstance("AES", "AndroidKeyStore").apply { init(KeyGenParameterSpec.Builder("crier", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes("GCM").setEncryptionPaddings("NoPadding").build()); generateKey() }
  return ks.getKey("crier", null) as SecretKey
 }
 fun save(value: JSONObject) {
  val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
  val encrypted = cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8))
  check(prefs.edit().putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP)).putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
 }
 fun read(): JSONObject {
  val data = prefs.getString("data", null) ?: return JSONObject()
  val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP))) }
  return JSONObject(String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP)), Charsets.UTF_8))
 }
}

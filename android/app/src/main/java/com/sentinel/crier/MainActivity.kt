package com.sentinel.crier
import android.app.Activity
import android.os.Bundle
import android.content.Intent
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.net.URI
import java.util.concurrent.Executors
class MainActivity:Activity() {
 private val io=Executors.newSingleThreadExecutor()
 private lateinit var panel:LinearLayout
 private lateinit var status:TextView
 private lateinit var journal:Journal
 private fun field(label:String,value:String="",secret:Boolean=false):EditText { panel.addView(TextView(this).apply { text=label }); return EditText(this).apply { setText(value); if(secret) inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; panel.addView(this) } }
 private fun button(label:String,action:()->Unit) { panel.addView(Button(this).apply { text=label; setOnClickListener { try { action() } catch(e:Exception) { status.text=e.message } } }) }
 private fun background(action:()->String) { io.submit { val message=try { action() } catch(e:Exception) { e.message ?: "Operation failed" }; runOnUiThread { status.text=message } } }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state); journal=Journal(this)
  panel=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(32,32,32,32) }
  setContentView(ScrollView(this).apply { addView(panel) })
  panel.addView(TextView(this).apply { text="Crier · native intent mirroring"; textSize=24f })
  status=TextView(this).apply { text=journal.meta("status").ifBlank { "Paused until enabled. Use paper credentials for testing." }; panel.addView(this) }
  val old=Vault(this).read()
  val pairing=field("Pair JSON: HTTPS url, token, environment, role",if(old.has("url")) JSONObject().put("url",old.optString("url")).put("token",old.optString("token")).put("environment",old.optString("environment")).put("role",old.optString("role")).toString() else "",true)
  val key=field("Your Alpaca API key",old.optString("key"),true); val secret=field("Your Alpaca secret",old.optString("secret"),true)
  val mode=field("Pricing: exact_limit / bounded_limit / market",old.optString("mode","exact_limit"))
  val bps=field("Maximum slippage basis points",old.optInt("bps",100).toString()); val amount=field("Maximum slippage dollars",old.optString("amount","0.02"))
  val age=field("Maximum entry age seconds (1–30)",old.optInt("age",10).toString()); val max=field("Maximum quantity (1–1000)",old.optInt("maxQuantity",1000).toString())
  val live=CheckBox(this).apply { text="I authorize LIVE account trading if environment is live"; panel.addView(this) }
  val market=CheckBox(this).apply { text="I explicitly enable market orders (price is not bounded)"; panel.addView(this) }
  button("Save and verify account") {
   require(!SyncService.active) { "Force-stop and reopen Crier before changing settings; active workers keep their verified configuration." }; val c=JSONObject(pairing.text.toString()); val uri=URI(c.getString("url"))
   require(uri.scheme=="https" && uri.host!=null && uri.userInfo==null && uri.query==null && uri.fragment==null)
   require(c.getString("role") in setOf("host","follower") && c.getString("environment") in setOf("paper","live"))
   require(c.getString("token").isNotBlank())
   require(c.getString("environment")!="live" || live.isChecked) { "Explicit live authorization required" }
   val pricing=mode.text.toString(); require(pricing in setOf("exact_limit","market","bounded_limit")); require(pricing!="market" || market.isChecked)
   require(age.text.toString().toInt() in 1..30 && max.text.toString().toInt() in 1..1000)
   c.put("key",key.text.toString()).put("secret",secret.text.toString()).put("mode",pricing).put("bps",bps.text.toString().toInt()).put("amount",amount.text.toString()).put("age",age.text.toString().toInt()).put("maxQuantity",max.text.toString().toInt())
   Policy.price("1",pricing,false,c.getInt("bps"),c.getString("amount"))
   background {
    c.put("account",Broker(c).account())
    val pinned=Vault(this).read(); if(pinned.has("account")) for(k in listOf("account","environment","role","url","token")) require(pinned.getString(k)==c.getString(k)) { "Pair/account identity is pinned to this journal. Use a separate app installation for another channel." }
    synchronized(SyncService::class.java) { require(!SyncService.active) { "Execution started while verifying. Settings were not changed." }; Vault(this).save(c) }
    "Saved ${c.getString("environment")} ${c.getString("role")}. Enable execution to start."
   }
  }
  button("Enable execution / Follow") { require(Vault(this).read().has("account")); getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",false).commit(); startForegroundService(Intent(this,SyncService::class.java)); status.text="Execution enabled" }
  button("Pause new entries (cancel/exit stay active)") { getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).commit(); status.text="New entries paused; exits and cancellation remain active" }
  panel.addView(TextView(this).apply { text="Host order entry · buy to open"; textSize=20f })
  val symbol=field("Symbol (stock or canonical OCC)"); val asset=field("Asset: stock / option","stock"); val qty=field("Quantity","1"); val price=field("Source limit price","1.00"); val trade=field("Trade UUID (filled automatically on enter)",journal.meta("lastTrade"))
  button("Select a journaled trade") { val records=journal.history(); android.app.AlertDialog.Builder(this).setTitle("Trade history").setItems(records.map { "${it.getString("symbol")} · ${it.getString("action")} · ${it.getString("trade_id").take(8)}" }.toTypedArray()) { _, index -> val selected=records[index]; symbol.setText(selected.getString("symbol")); asset.setText(selected.getString("asset")); qty.setText(selected.getInt("quantity").toString()); price.setText(selected.getString("limit_price")); trade.setText(selected.getString("trade_id")) }.show() }
  for(action in listOf("enter","replace","cancel","exit")) button(action.replaceFirstChar { it.uppercase() }) {
   val c=Vault(this).read(); require(c.getString("role")=="host") { "Only host creates intents" }
   require(action !in setOf("enter","replace") || !getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) { "Enable execution first" }
   val e=if(action=="enter") journal.create(action,symbol.text.toString().trim().uppercase(),asset.text.toString(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment")) else journal.create(action,symbol.text.toString().trim().uppercase(),asset.text.toString(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment"),trade.text.toString())
   trade.setText(e.getString("trade_id")); journal.setMeta("lastTrade",e.getString("trade_id")); startForegroundService(Intent(this,SyncService::class.java)); status.text="Journaled $action; broker and relay dispatch independently"
  }
  button("Refresh journal status") { status.text=journal.meta("status")+"\n"+journal.summary() }
  panel.addView(TextView(this).apply { text="Keep Crier running for mirroring. Android may stop background data sync; reopen to resume. Unknown broker outcomes remain blocked until reconciled. Cancel stops the unfilled remainder; Exit closes only this trade’s acquired holdings." })
 }
 override fun onDestroy() { io.shutdown(); super.onDestroy() }
}

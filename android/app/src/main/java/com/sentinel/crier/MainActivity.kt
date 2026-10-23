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
 private var pendingExport:String?=null
 private lateinit var panel:LinearLayout
 private lateinit var status:TextView
 private lateinit var journal:Journal
 private fun field(label:String,value:String="",secret:Boolean=false):EditText { panel.addView(TextView(this).apply { text=label }); return EditText(this).apply { setText(value); if(secret) inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; panel.addView(this) } }
 private fun button(label:String,action:()->Unit) { panel.addView(Button(this).apply { text=label; setOnClickListener { try { action() } catch(e:Exception) { status.text=e.message } } }) }
 private fun background(action:()->String) { io.submit { val message=try { action() } catch(e:Exception) { e.message ?: "Operation failed" }; runOnUiThread { status.text=message } } }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state); journal=Journal(this)
  if(android.os.Build.VERSION.SDK_INT>=33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED) requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS),42)
  panel=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(32,32,32,32) }
  setContentView(ScrollView(this).apply { addView(panel) })
  panel.addView(TextView(this).apply { text="Crier Â· native intent mirroring"; textSize=24f })
  status=TextView(this).apply { text=journal.meta("status").ifBlank { "Paused until enabled. Use paper credentials for testing." }; panel.addView(this) }
  val old=Vault(this).read()
  var candidate=JSONObject(old.toString())
  var newConnection=false
  val environment=field("Account environment: paper / live",old.optString("environment","paper"))
  val service=field("Connection service HTTPS URL (Advanced; or use invitation link)",old.optString("url",QuickConnection.defaultOrigin(this)))
  val invitation=field("Receiver invitation link or 16-character code","",true)
  val key=field("Your Alpaca API key",old.optString("key"),true); val secret=field("Your Alpaca secret",old.optString("secret"),true)
  val mode=field("Pricing: exact_limit / bounded_limit / market",old.optString("mode","exact_limit"))
  val bps=field("Maximum slippage basis points",old.optInt("bps",100).toString()); val amount=field("Maximum slippage dollars",old.optString("amount","0.02"))
  val age=field("Maximum entry age seconds (1–30)",old.optInt("age",10).toString()); val max=field("Maximum quantity (1–1000)",old.optInt("maxQuantity",1000).toString())
  val live=CheckBox(this).apply { text="I authorize LIVE account trading if environment is live"; panel.addView(this) }
  val market=CheckBox(this).apply { text="I explicitly enable market orders (price is not bounded)"; isChecked=old.optString("mode")=="market"; panel.addView(this) }
  val separateAccount=CheckBox(this).apply { text="Save a different account in a separate journal on this connection. Restore the old profile to manage its outstanding orders."; panel.addView(this) }
  fun requireStopped() { require(!SyncService.active) { "Tap Stop workers for settings/recovery, then wait for stopped status." } }
  button("Stop workers for settings / recovery") {
   getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()
   stopService(Intent(this,SyncService::class.java))
   background { val deadline=System.currentTimeMillis()+45000; while(SyncService.active && System.currentTimeMillis()<deadline) Thread.sleep(100); requireStopped(); "Workers stopped. Credentials and connections can be changed; all journals retained." }
  }
  button("Host · create a new connection") {
   requireStopped(); val env=environment.text.toString().trim(); require(env in setOf("paper","live")); require(env!="live" || live.isChecked) { "Explicit live authorization required" }; val url=service.text.toString()
   background { candidate=QuickConnection.host(url,env); newConnection=true; "Host connection created. Save and verify account, then create a receiver invitation." }
  }
  button("Receive · join by invitation") {
   requireStopped(); val env=environment.text.toString().trim(); require(env in setOf("paper","live")); require(env!="live" || live.isChecked) { "Explicit live authorization required" }; val invite=QuickConnection.invitation(invitation.text.toString(),service.text.toString())
   background { candidate=QuickConnection.receive(invite,env); newConnection=true; "Receiver connected. Save and verify your own account to finish setup." }
  }
  button("Save and verify account / rotate broker credentials") {
   requireStopped(); val c=if(newConnection) JSONObject(candidate.toString()) else Vault(this).read(); require(c.has("token")) { "Host or Receive first" }
   require(c.getString("environment")==environment.text.toString().trim()) { "Environment changes need a new connection" }
   require(c.getString("environment")!="live" || live.isChecked) { "Explicit live authorization required" }
   val pricing=mode.text.toString(); require(pricing in setOf("exact_limit","market","bounded_limit")); require(pricing!="market" || market.isChecked)
   require(age.text.toString().toInt() in 1..30 && max.text.toString().toInt() in 1..1000)
   c.put("key",key.text.toString()).put("secret",secret.text.toString()).put("mode",pricing).put("bps",bps.text.toString().toInt()).put("amount",amount.text.toString()).put("age",age.text.toString().toInt()).put("maxQuantity",max.text.toString().toInt())
   Policy.price("1",pricing,false,c.getInt("bps"),c.getString("amount"))
   val createProfile=newConnection || separateAccount.isChecked
   background {
    c.put("account",Broker(c).account())
    synchronized(SyncService::class.java) { requireStopped(); Vault(this).save(c,createProfile) }
    newConnection=false; candidate=JSONObject(c.toString()); journal=Journal(this)
    "Saved ${c.getString("environment")} ${c.getString("role")}. Journal retained. Enable execution to reconcile and start."
   }
  }
  button("Restore a saved connection / account journal") {
   requireStopped(); val profiles=Vault(this).profiles()
   android.app.AlertDialog.Builder(this).setTitle("Saved connections · journals are retained").setItems(profiles.map { val c=it.getJSONObject("config"); "${c.optString("environment")} ${c.optString("role")} · account ${c.optString("account").take(8)} · ${it.getString("id").take(8)}" }.toTypedArray()) { _,index ->
    try { requireStopped(); Vault(this).select(profiles[index].getString("id")); recreate() } catch(e:Exception) { status.text=e.message }
   }.show()
  }
  button("Create and share receiver invitation (expires in 10 minutes)") {
   val c=Vault(this).read(); require(c.optString("role")=="host") { "Only a saved Host creates invitations" }
   background { val link=QuickConnection.invite(c); runOnUiThread { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { type="text/plain"; putExtra(Intent.EXTRA_TEXT,link) },"Share receiver invitation")) }; "Invitation ready; single use, expires in 10 minutes." }
  }
  button("Receivers · review and revoke") {
   val c=Vault(this).read(); require(c.optString("role")=="host") { "Only the host can revoke receivers" }
   background { val list=QuickConnection.receivers(c); runOnUiThread {
    android.app.AlertDialog.Builder(this).setTitle("Tap receiver to revoke access").setItems((0 until list.length()).map { val r=list.getJSONObject(it); "${r.getString("id")} · ${if(r.optInt("revoked")==1) "revoked" else "active"}" }.toTypedArray()) { _,i -> val r=list.getJSONObject(i)
     android.app.AlertDialog.Builder(this).setTitle("Revoke receiver?").setMessage("Stops future relay access. Orders already submitted remain at the receiver's broker and must be inspected there.").setPositiveButton("Revoke") { _,_ -> background { QuickConnection.revoke(c,r.getString("id")); "Receiver revoked" } }.setNegativeButton("Cancel",null).show()
    }.show()
   }; "${list.length()} receiver records" }
  }
  button("Enable execution / Follow / reconnect") { require(Vault(this).read().has("account")); getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",false).putBoolean("enabled",true).commit(); if(!SyncService.active) startForegroundService(Intent(this,SyncService::class.java)); status.text="Reconnecting; broker orders are reconciled before new work" }
  button("Pause new entries (cancel/exit stay active)") { getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).commit(); status.text="New entries paused; exits and cancellation remain active" }
  discordSettings(old)
  button("Unresolved orders and recovery status") { android.app.AlertDialog.Builder(this).setTitle("Execution and connection recovery").setMessage("${journal.meta("visibility")}\n${journal.meta("service")}\n${journal.meta("connection")}\n${journal.meta("status")}\n${journal.meta("protocolStatus")}\n${journal.unresolved()}\nRetain this journal. Never clear app data to resolve an unknown broker outcome.").setPositiveButton("Close",null).show() }
  panel.addView(TextView(this).apply { text="Host order entry Â· buy to open"; textSize=20f })
  val symbol=field("Symbol (stock or canonical OCC)"); val asset=field("Asset: stock / option","stock"); val qty=field("Quantity","1"); val price=field("Source limit price","1.00"); val trade=field("Trade UUID (filled automatically on enter)",journal.meta("lastTrade"))
  button("Select a journaled trade") { val records=journal.history(); android.app.AlertDialog.Builder(this).setTitle("Trade history").setItems(records.map { "${it.getString("symbol")} Â· ${it.getString("action")} Â· ${it.getString("trade_id").take(8)}" }.toTypedArray()) { _, index -> val selected=records[index]; symbol.setText(selected.getString("symbol")); asset.setText(selected.getString("asset")); qty.setText(selected.getInt("quantity").toString()); price.setText(selected.getString("limit_price")); trade.setText(selected.getString("trade_id")) }.show() }
  for(action in listOf("enter","replace","cancel","exit")) button(action.replaceFirstChar { it.uppercase() }) {
   val c=Vault(this).read(); require(c.getString("role")=="host") { "Only host creates intents" }
   require(action !in setOf("enter","replace") || !getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) { "Enable execution first" }
   val e=if(action=="enter") journal.create(action,symbol.text.toString().trim().uppercase(),asset.text.toString(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment")) else journal.create(action,symbol.text.toString().trim().uppercase(),asset.text.toString(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment"),trade.text.toString())
   trade.setText(e.getString("trade_id")); journal.setMeta("lastTrade",e.getString("trade_id")); if(!SyncService.active) startForegroundService(Intent(this,SyncService::class.java)); status.text="Journaled $action; broker and relay dispatch independently"
  }
  button("Diagnostics Â· timeline, premiums and latency") { val records=Diagnostics.export(journal); android.app.AlertDialog.Builder(this).setTitle("Execution diagnostics").setItems((0 until records.length()).map { val e=records.getJSONObject(it).getJSONObject("event"); "${e.getString("symbol")} ${e.getString("action")} Â· ${e.getString("event_id").take(8)}" }.toTypedArray()) { _, i -> android.app.AlertDialog.Builder(this).setTitle("Event evidence").setMessage(Diagnostics.describe(records.getJSONObject(i))).setPositiveButton("Close",null).show() }.show() }
  button("Share diagnostics JSON") { shareDiagnostics(false) }
  button("Share diagnostics CSV") { shareDiagnostics(true) }
  button("Save diagnostics JSON file") { saveDiagnostics(false) }
  button("Save diagnostics CSV file") { saveDiagnostics(true) }
  button("Refresh journal status") { status.text="${if(SyncService.active) "Workers active" else "Workers stopped / suspended"} · ${if(getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) "entries paused" else "entries enabled"}\n${journal.meta("visibility")}\n${journal.meta("service")}\n${journal.meta("connection")}\n${journal.meta("status")}\n${journal.meta("protocolStatus")}\n${journal.summary()}\nDiscord: ${journal.alertSummary()} ${journal.meta("discordStatus")}" }
  panel.addView(TextView(this).apply { text="Keep Crier running for mirroring. Android may stop background data sync; reopen to resume. Unknown broker outcomes remain blocked until reconciled. Cancel stops the unfilled remainder; Exit closes only this tradeâ€™s acquired holdings." })
 }
 private fun discordSettings(old:JSONObject) {
  panel.addView(TextView(this).apply { text="Discord alerts"; textSize=20f })
  val webhook=field("Discord webhook URL (stored encrypted)",old.optString("discordWebhook"),true)
  val style=field("Format: card / plain",old.optString("discordStyle","card"))
  val template=field("Template: {action} {symbol}; fields: symbol, action, quantity, price, status, trade_id",old.optString("discordTemplate","{action} {symbol}"))
  val selections=Discord.fields.associateWith { name -> CheckBox(this).apply { text="Show $name"; isChecked=name in old.optString("discordFields",Discord.fields.joinToString(",")).split(','); panel.addView(this) } }
  fun settings():JSONObject { val c=Vault(this).read(); c.put("discordWebhook",if(webhook.text.toString().isBlank()) "" else Discord.destination(webhook.text.toString())); require(style.text.toString() in setOf("card","plain")); c.put("discordStyle",style.text.toString()).put("discordTemplate",template.text.toString()).put("discordFields",selections.filterValues { it.isChecked }.keys.joinToString(",")); Discord.preview(c); return c }
  button("Preview Discord message") { android.app.AlertDialog.Builder(this).setTitle("Preview · TEST provenance").setMessage(Discord.readablePreview(settings())).setPositiveButton("Close",null).show() }
  button("Save Discord destination and template") { require(!SyncService.active) { "Stop workers to apply settings safely" }; val c=settings(); require(c.has("account")) { "Verify account first" }; require(c.optString("discordWebhook")==Vault(this).read().optString("discordWebhook") || !journal.hasUndeliveredAlerts()) { "Queued alerts belong to the current destination. Deliver or explicitly discard them before changing it." }; Vault(this).save(c); status.text="Discord settings saved. Reconnect to resume delivery." }
  button("Queue test message") { require(Vault(this).read().optString("discordWebhook").isNotBlank()) { "Save a Discord destination first" }; val id=Discord.test(journal); background { Discord.deliver(journal,Vault(this).read(),jobId=id); "Discord: ${journal.alertSummary()} · ${journal.meta("discordStatus")}" } }
  button("Retry Discord deliveries") { require(!SyncService.active) { "Stop workers before inspecting and retrying uncertain deliveries" }; android.app.AlertDialog.Builder(this).setTitle("Retry deliveries?").setMessage("Some messages may already exist in Discord after a lost acknowledgement. Inspect the channel first. Retrying uncertain messages can create duplicates.").setPositiveButton("Retry; accept duplicate risk") { _,_ -> journal.retryAlerts(); background { Discord.deliver(journal,Vault(this).read()); "Discord: ${journal.alertSummary()} · ${journal.meta("discordStatus")}" } }.setNegativeButton("Cancel",null).show() }
  button("Discard queued Discord messages before changing destination") { require(!SyncService.active) { "Stop workers first" }; android.app.AlertDialog.Builder(this).setTitle("Discard undelivered messages?").setMessage("Messages will not be retried. Execution journals and message evidence remain retained.").setPositiveButton("Discard") { _,_ -> journal.discardAlerts(); status.text="Queued messages discarded; destination can now be changed" }.setNegativeButton("Cancel",null).show() }
  val observation=field("Manual observation text (explicitly unverified)")
  button("Publish manual observation") { val text=observation.text.toString().trim(); require(text.isNotBlank() && text.length<=500); journal.enqueueAlert("manual:${java.util.UUID.randomUUID()}",Discord.record("manual",JSONObject().put("symbol",text).put("action","observation"))); status.text="Manual observation queued; never labelled as a broker fill" }
 }
 override fun onPause() { if(::journal.isInitialized) journal.setMeta("visibility","App in background; Android may suspend or stop syncing"); super.onPause() }
 override fun onResume() { super.onResume(); if(::journal.isInitialized) journal.setMeta("visibility","App foreground"); if(::journal.isInitialized && Vault(this).read().has("account") && !SyncService.active && getSharedPreferences("controls",MODE_PRIVATE).getBoolean("enabled",false)) { startForegroundService(Intent(this,SyncService::class.java)); status.text="Foreground resume · reconciling broker orders before new work" } }
 private fun saveDiagnostics(csv:Boolean) { val records=Diagnostics.export(journal); pendingExport=if(csv) Diagnostics.csv(records) else records.toString(2); startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type=if(csv) "text/csv" else "application/json"; putExtra(Intent.EXTRA_TITLE,if(csv) "crier-diagnostics.csv" else "crier-diagnostics.json") },41) }
 override fun onActivityResult(request:Int,result:Int,data:Intent?) { super.onActivityResult(request,result,data); if(request==41 && result==RESULT_OK) { val text=pendingExport ?: return; data?.data?.let { uri -> background { contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray(Charsets.UTF_8)) } ?: error("Unable to write export"); "Diagnostics exported" } }; pendingExport=null } }
 private fun shareDiagnostics(csv:Boolean) { val records=Diagnostics.export(journal); val text=if(csv) Diagnostics.csv(records) else records.toString(2); startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { type=if(csv) "text/csv" else "application/json"; putExtra(Intent.EXTRA_SUBJECT,"Crier execution diagnostics"); putExtra(Intent.EXTRA_TEXT,text) },"Share diagnostics")) }
 override fun onDestroy() { io.shutdown(); super.onDestroy() }
}

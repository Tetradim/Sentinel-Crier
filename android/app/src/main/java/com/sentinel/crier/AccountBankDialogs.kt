package com.sentinel.crier

import android.app.Activity
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.util.concurrent.Executor

/** Account allocation observations and dialogs, scoped to one visible account selection. */
class AccountBankDialogs(
 private val activity:Activity,
 private val routeId:String,
 private val config:JSONObject,
 worker:Executor,
 private val current:()->Boolean,
 private val message:(String)->Unit,
 private val workersActive:()->Boolean={ SyncService.active }
) {
 private val read=ScopedRead(worker,Executor { activity.runOnUiThread(it) })
 private fun background(action:()->String) {
  read.load(current,action,message,{ message(it.message ?: "Account operation failed") })
 }
 fun show() {
  require(config.has("account")) { "Save and verify a Trade / Follow account first" }
  val bank=AndroidAccountBank.bank(activity); val scope=RouteAccounts.key(config)
  if(!bank.enabled(scope)) {
   android.app.AlertDialog.Builder(activity).setTitle("Set up account ID bank")
    .setMessage("Stop every connection first. Setup checks all retained journals and refuses unresolved orders or older Crier holdings. External holdings remain separate. IDs and source ownership are permanent; never clear app data. New host pools start at zero and require bounded limit pricing. Setup keeps every connection stopped and paused. This coordinates this installation only.")
    .setPositiveButton("Verify and set up") { _,_ -> background { AndroidAccountBank.setup(activity,config) } }.setNegativeButton("Close",null).show(); return
  }
  read.load(current,{ bank.report(scope) },{ report ->
  showReport(report)
  },{ message(it.message ?: "Account ledger unavailable") })
 }
 private fun showReport(report:JSONObject) {
  val scope=RouteAccounts.key(config)
  fun lots(name:String):String { val a=report.getJSONArray(name); return (0 until a.length()).joinToString("\n") { i -> val r=a.getJSONObject(i); "ID ${r.getInt("id")} · host ${r.getString("route")} · ${r.getString("symbol")} · owned ${r.getInt("units")} · pending buy ${r.getInt("pending_buy")} / exit ${r.getInt("pending_exit")}" }.ifBlank { "None" } }
  android.app.AlertDialog.Builder(activity).setTitle("Account ID bank")
   .setMessage("$scope\n${report.getString("blocked").ifBlank { "Local ledger has no recorded block. Broker verification is a separate check." }}\n\nActive IDs\n${lots("active")}\n\nArchived IDs (never reused)\n${lots("archived")}\n\nEditing pools changes this selected host only. Exits can use only its owned units.")
   .setPositiveButton("Edit this host's pools") { _,_ -> editPools() }
   .setNeutralButton("Check broker and guide recovery") { _,_ -> background {
    val checked=SyncService.withBankTransition(beforeCheck={ AndroidAccountBank.pauseRoutes(activity,config) }) { AndroidAccountBank.managed(activity,routeId,config,Broker(config)).recovery() }
    activity.runOnUiThread { if(!current()) return@runOnUiThread;
     val errors=checked.getJSONArray("errors"); val instructions=(0 until errors.length()).joinToString("\n") { errors.getString(it) }
     android.app.AlertDialog.Builder(activity).setTitle("Account recovery · retained evidence")
      .setMessage("${if(checked.getBoolean("broker_checked")) "Broker evidence checked" else "Recovery unresolved"}\n${checked.getString("blocked")}\n$instructions\n\nBroker positions: ${checked.opt("broker_positions")}\nExternal baseline: ${checked.getJSONObject("baseline")}\n\n1. Keep entries paused and preserve this installation and each original route.\n2. Inspect the exact account/environment, original client IDs, cumulative fills and broker positions. Unknown outcomes never permit another POST.\n3. Restore the owning route for authorized cancel/exit handling. Partial canceled fills remain owned.\n4. Recheck after broker evidence settles. Matching inventory clears only an inventory discrepancy; contradictory fills require investigation. There is no clear-ID or automatic retry control.")
      .setNeutralButton("Verify flat and repair") { _,_ -> background {
       SyncService.withBankTransition(beforeCheck={ AndroidAccountBank.pauseRoutes(activity,config) }) {
        AndroidAccountBank.managed(activity,routeId,config,Broker(config)).repairFlat()
        "Authoritative flat repair completed. IDs, original orders and journals retained. All routes remain stopped and paused."
       }
      } }.setPositiveButton("Close",null).show()
    }; "Recovery check finished; no orders submitted."
   } }.setNegativeButton("Close",null).show()
 }
 internal fun editPools() {
  if(workersActive()) {
   message("Stop every connection and wait for workers to drain before editing host pools")
   android.app.AlertDialog.Builder(activity).setTitle("Stop connections to edit pools")
    .setMessage("Use Stop all connections, wait for stopped status, then reopen the account bank. Existing broker orders remain active.")
    .setPositiveButton("Close",null).show()
   return
  }
  val bank=AndroidAccountBank.bank(activity); val scope=RouteAccounts.key(config)
  read.load(current,{ bank.report(scope).getJSONObject("policies") },{ policies ->
   if(workersActive()) message("Connections started; stop every connection before editing pools")
   else showPools(policies)
  },{ message(it.message ?: "Account ledger unavailable") })
 }
 private fun showPools(policies:JSONObject) {
  val bank=AndroidAccountBank.bank(activity); val scope=RouteAccounts.key(config)
  val layout=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL; setPadding(24,12,24,12) }
  layout.addView(TextView(activity).apply { text="Host $routeId\nPools are aggregate exposure ceilings; entry sizing remains separate. Reducing a pool never liquidates holdings. Zero blocks new entries. Fees reserve once per order. Losses reduce monetary capacity; fixed dollar pools do not grow with profits." })
  val inputs=mutableListOf<Triple<String,Spinner,Pair<EditText,EditText>>>()
  for(asset in listOf("stock","option")) {
   val p=policies.optJSONObject("$routeId:$asset") ?: JSONObject().put("mode","dollars").put("value","0").put("fee","0")
   layout.addView(TextView(activity).apply { text="${asset.replaceFirstChar { it.uppercase() }} pool" })
   val modes=listOf("units","dollars","equity_percent"); val picker=Spinner(activity).apply { adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,listOf("Shares / contracts","Dollars","Account equity %")); setSelection(modes.indexOf(p.getString("mode"))); layout.addView(this) }
   val value=EditText(activity).apply { hint="Pool value"; setText(p.getString("value")); inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL; layout.addView(this) }
   val fee=EditText(activity).apply { hint="Fee reserve dollars per order"; setText(p.getString("fee")); inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL; layout.addView(this) }
   inputs.add(Triple(asset,picker,Pair(value,fee)))
  }
  android.app.AlertDialog.Builder(activity).setTitle("This host's allocation pools").setView(ScrollView(activity).apply { addView(layout) }).setPositiveButton("Save pools; stay stopped") { _,_ ->
   try { SyncService.withBankTransition { for((asset,picker,values) in inputs) bank.configure(scope,routeId,asset,listOf("units","dollars","equity_percent")[picker.selectedItemPosition],values.first.text.toString(),values.second.text.toString()) }; message("Host pools saved. Explicitly reconnect each route to resume.") } catch(e:Exception) { message(e.message ?: "Pool save failed") }
  }.setNegativeButton("Close",null).show()
 }
}

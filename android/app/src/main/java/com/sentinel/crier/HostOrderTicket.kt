package com.sentinel.crier

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.widget.*

/** Source-intent ticket. Review never bypasses the executor's account, sizing or admission checks. */
class HostOrderTicket(private val activity:Activity,private val panel:LinearLayout,
 private val journal:Journal,private val message:(String)->Unit) {
 private fun field(label:String,value:String="",numeric:Boolean=false):EditText {
  val input=EditText(activity).apply { id=android.view.View.generateViewId(); hint=label; setText(value); if(numeric) inputType=InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL }
  panel.addView(TextView(activity).apply { text=label; labelFor=input.id }); panel.addView(input); return input
 }
 private fun button(label:String,action:()->Unit) { panel.addView(Button(activity).apply { text=label; setOnClickListener { try { action() } catch(error:Exception) { message(error.message ?: "Check ticket details") } } }) }
 fun build():android.view.View {
  val title=TextView(activity).apply { text="TRADE / SOURCE INTENT"; textSize=20f; panel.addView(this) }
  panel.addView(TextView(activity).apply { text="Enter an exact stock ticker or full OCC option contract. Source intent is not a quote or a fill." })
  val symbol=field("Symbol (stock or canonical OCC)")
  val selection=SetupChoices.instrument.forSaved("stock")
  panel.addView(TextView(activity).apply { text="Instrument" })
  val asset=Spinner(activity).apply { adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,selection.labels); panel.addView(this) }
  val qty=field("Quantity","1",true); val price=field("Source limit price","",true)
  val trade=field("Trade UUID (filled automatically on enter)",journal.meta("lastTrade"))
  button("Select a journaled trade") {
   val records=journal.history()
   AlertDialog.Builder(activity).setTitle("Trade history").setItems(records.map { "${it.getString("symbol")} / ${it.getString("action")} / ${it.getString("trade_id").take(8)}" }.toTypedArray()) { _,index ->
    val e=records[index]; symbol.setText(e.getString("symbol")); asset.setSelection(SetupChoices.instrument.forSaved(e.getString("asset")).selectedIndex); qty.setText(e.getInt("quantity").toString()); price.setText(e.getString("limit_price")); trade.setText(e.getString("trade_id"))
   }.show()
  }
  for((action,label) in listOf("enter" to "Buy / open","replace" to "Replace buy intent","cancel" to "Cancel unfilled remainder","exit" to "Sell tracked units")) button(label) {
   val config=Vault(activity).read(); requireHost(action)
   val ticker=symbol.text.toString().trim().uppercase(); val instrument=selection.requireValue(asset.selectedItemPosition)
   val quantity=qty.text.toString().toInt(); require(quantity in 1..1000)
   val limit=price.text.toString(); require(limit.toBigDecimal().signum()>0)
   val tradeId=trade.text.toString(); if(action!="enter") require(java.util.UUID.fromString(tradeId).toString()==tradeId)
   AlertDialog.Builder(activity).setTitle("Review $label")
    .setMessage("${config.getString("environment").uppercase()} / Account ${config.getString("account")}\n\n$ticker\n$instrument / $quantity units\nSource limit: $$limit\nAction: $action\n${if(action=="enter") "New tracked trade" else "Trade $tradeId"}\n\nThis journals a source instruction. Broker fills and follower sizing may differ.")
    .setPositiveButton("Confirm instruction") { _,_ ->
     try {
      requireHost(action); val current=Vault(activity).read(); require(Settings.sameIdentity(config,current)) { "Selected account changed; review again" }
      val e=if(action=="enter") journal.create(action,ticker,instrument,quantity,limit,current.getString("environment")) else journal.create(action,ticker,instrument,quantity,limit,current.getString("environment"),tradeId)
      trade.setText(e.getString("trade_id")); journal.setMeta("lastTrade",e.getString("trade_id"))
      if(!SyncService.active(activity)) SyncService.requestStart(activity)
      message("Journaled $action; broker and relay dispatch independently")
     } catch(error:Exception) { message(error.message ?: "Instruction not accepted") }
    }.setNegativeButton("Back to ticket",null).show()
  }
  return title
 }
 private fun requireHost(action:String) {
  require(Vault(activity).read().optString("role")=="host") { "Only host creates intents" }
  require(action !in setOf("enter","replace") || !activity.getSharedPreferences("controls",0).getBoolean("paused",true)) { "Enable execution first" }
 }
}

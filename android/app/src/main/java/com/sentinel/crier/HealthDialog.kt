package com.sentinel.crier

import android.app.Activity
import android.app.AlertDialog
import android.widget.ScrollView
import android.widget.TextView

object HealthDialog {
 fun show(activity:Activity,health:ComponentHealth,journey:String,visible:()->Boolean={true},recover:(Int)->Unit) {
  val text=TextView(activity).apply { setPadding(24,20,24,20); textSize=15f; setTextIsSelectable(true) }
  fun refresh() { text.text=ComponentHealth.describe(health.snapshot(health.context(journey)),health.unavailable) }
  refresh()
  val scroll=ScrollView(activity).apply { addView(text) }
  val dialog=AlertDialog.Builder(activity).setTitle("Connection health").setView(scroll)
   .setPositiveButton("Refresh view",null).setNegativeButton("Close",null)
   .setNeutralButton("Recovery actions") { _,_ ->
    AlertDialog.Builder(activity).setTitle("Recovery · no automatic sends")
     .setItems(arrayOf("Account setup on this screen","Saved order evidence","Discord delivery evidence","Stop local workers")) { _,index -> recover(index) }.setNegativeButton("Close",null).show()
   }.create()
  val ticker=object:Runnable {
   override fun run() {
    if(!dialog.isShowing || activity.isDestroyed || activity.isFinishing) return
    if(!visible()) { dialog.dismiss(); return }
    refresh(); text.postDelayed(this,1000)
   }
  }
  dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener { refresh() }; text.post(ticker) }
  dialog.setOnDismissListener { text.removeCallbacks(ticker) }
  dialog.show()
 }
}

package com.sentinel.crier
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.widget.Toast

fun Activity.showPracticeGuide() {
 val guide=assets.open("customer-practice.json").bufferedReader().use { PracticeGuide.parse(it.readText()) }
 AlertDialog.Builder(this).setTitle("Optional paper practice")
  .setItems(guide.journeys.map { it.title }.toTypedArray()) { _,index ->
   AlertDialog.Builder(this).setTitle(guide.journeys[index].title).setMessage(guide.format(guide.journeys[index].id))
    .setPositiveButton("Return to setup",null)
    .setNeutralButton("Open support") { _,_ ->
     runCatching { startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(PracticeGuide.SUPPORT))) }
      .onFailure { Toast.makeText(this,"Open the Sentinel-Crier GitHub Issues page in your browser.",Toast.LENGTH_LONG).show() }
    }.show()
  }.setNegativeButton("Close",null).show()
}

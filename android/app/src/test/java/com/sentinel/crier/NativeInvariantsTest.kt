package com.sentinel.crier

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.time.Instant

/** Adapts shared inputs to production APIs; expected outcomes live only in the fixture. */
class NativeInvariantsTest {
 private fun fixture() = JSONObject(requireNotNull(javaClass.getResourceAsStream("/native-invariants.json")).bufferedReader().use { it.readText() }).also { require(it.getInt("version")==1) { "Unsupported native-invariants fixture version" } }
 @Test fun sharedClock() {
  val cases=fixture().getJSONArray("clock")
  for(i in 0 until cases.length()) {
   val case=cases.getJSONObject(i); var wall=case.getLong("anchor_wall_ms"); var mono=case.getLong("anchor_mono_ms")
   val clock=EntryClock({ Instant.ofEpochMilli(wall) }, { mono })
   val samples=case.getJSONArray("samples")
   for(j in 0 until samples.length()) {
    val sample=samples.getJSONObject(j); wall=sample.getLong("wall_ms"); mono=sample.getLong("mono_ms")
    val reading=clock.read(); val context="${case.getString("id")} sample $j"
    if(sample.optBoolean("uncertain")) assertNull(context,reading)
    else { assertNotNull(context,reading); assertEquals(context,sample.getLong("effective_ms"),reading!!.effective.toEpochMilli()); assertEquals(context,wall,reading.wall.toEpochMilli()) }
   }
  }
 }
 @Test fun sharedBank() {
  val cases=fixture().getJSONArray("bank")
  for(i in 0 until cases.length()) {
   val case=cases.getJSONObject(i); val directory=Files.createTempDirectory("shared-bank").toFile()
   try {
    val file=directory.resolve("bank.json"); var bank=AccountBank(file)
    fun scope(account:String)="alpaca:paper:$account"
    for(account in listOf("one","two")) {
     bank.enable(scope(account),"100","100",emptyMap())
     for(route in listOf("alice","bob")) bank.configure(scope(account),route,"stock","dollars","100","0")
    }
    val reservations=mutableMapOf<String,Pair<String,JSONObject>>()
    val steps=case.getJSONArray("steps")
    for(j in 0 until steps.length()) {
     val step=steps.getJSONObject(j); val op=step.getString("op"); val context="${case.getString("id")} step $j"
     if(op=="restart") { bank=AccountBank(file); continue }
     val scope=scope(step.optString("account","one"))
     val perform:()->Unit = {
      when(op) {
       "reserve" -> {
        val event=JSONObject().put("trade_id",step.getString("trade")).put("event_id",step.getString("event")).put("symbol","SPY").put("asset","stock").put("environment","paper")
        val cid=bank.reserve(scope,step.getString("route"),event,0,step.getInt("quantity"),step.getBoolean("sell"),"10",1,"100","100")
        reservations[step.getString("alias")]=cid to step
       }
       "observe" -> {
        val (cid,original)=reservations.getValue(step.getString("alias"))
        bank.observe(scope,cid,JSONObject().put("id","broker-$cid").put("client_order_id",cid).put("symbol","SPY").put("side",if(original.getBoolean("sell")) "sell" else "buy").put("qty",original.getInt("quantity").toString()).put("filled_qty",step.getInt("filled").toString()).put("filled_avg_price","10").put("status",step.getString("status")))
       }
       "inventory" -> { val positions=step.getJSONObject("positions"); bank.inventory(scope,positions.keys().asSequence().associateWith { positions.getInt(it) }) }
       else -> require(op=="check")
      }
     }
     if(step.optBoolean("refused")) assertThrows(context,IllegalArgumentException::class.java) { perform() } else perform()
     val report=bank.report(scope)
     assertEquals(context,0,report.getString("available").toBigDecimal().compareTo(step.getString("available").toBigDecimal()))
     assertEquals(context,step.getInt("active"),report.getJSONArray("active").length())
     assertEquals(context,step.getInt("orders"),bank.orders(scope).size)
     assertEquals(context,step.optBoolean("blocked"),report.getString("blocked").isNotEmpty())
     if(op=="observe") {
      val (cid,original)=reservations.getValue(step.getString("alias")); val order=bank.orders(scope).single { it.getString("cid")==cid }
      assertEquals(context,step.optInt("expected_filled",step.getInt("filled")),order.getInt("filled")); assertEquals(context,step.getString("status"),order.getString("status"))
      val lots=listOf(report.getJSONArray("active"),report.getJSONArray("archived")).flatMap { array -> (0 until array.length()).map { array.getJSONObject(it) } }
      val owner=lots.single { it.getInt("id")==order.getInt("bank_id") }
      assertEquals(context,original.getString("route"),owner.getString("route")); assertEquals(context,original.getString("trade"),owner.getString("trade"))
     }
    }
   } finally { directory.deleteRecursively() }
  }
 }
}

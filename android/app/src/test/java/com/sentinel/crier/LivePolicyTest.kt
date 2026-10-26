package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
class LivePolicyTest {
 @Test fun strictPolicyAndDollarMath() {
  assertEquals(7,LivePolicy.target(JSONObject("""{"mode":"budget","budget":"150"}"""),10,"0.20",100,0,java.math.BigDecimal.ZERO))
  assertEquals(0,LivePolicy.target(JSONObject("""{"mode":"ratio","ratio_bps":5000}"""),1,"1",1,0,java.math.BigDecimal.ZERO))
  for(raw in listOf("""{"version":null}""","""{"mode":null}""","""{"max_source_quantity":null}""","""{"max_local_quantity":null}""","""{"exit_mode":null}""","""{"mode":"budget","budget":"01"}""","""{"mode":"budget","budget":"12345678901234567890.1"}""","""{"fixed_quantity":true,"mode":"fixed"}""","""{"mode":"ratio","ratio_bps":1.5}""","""{"budget":"1","mode":"source"}""","""{"extra":1}""")) assertThrows(IllegalArgumentException::class.java) { LivePolicy.validate(JSONObject(raw)) }
 }
 @Test fun completeSourceIntentHistoryIsRequired() {
  fun e(seq:Int,action:String,q:Int)=JSONObject().put("sequence",seq).put("action",action).put("quantity",q).put("symbol","SPY").put("asset","stock").put("environment","paper").put("trade_id","trade")
  assertEquals(Pair(10,5),LivePolicy.sourceIntent(listOf(e(1,"enter",10),e(2,"exit",2),e(3,"exit",3))))
  assertThrows(IllegalArgumentException::class.java) { LivePolicy.sourceIntent(listOf(e(1,"enter",10),e(3,"exit",3))) }
 }
}

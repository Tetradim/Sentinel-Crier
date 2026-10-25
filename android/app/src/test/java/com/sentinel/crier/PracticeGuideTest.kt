package com.sentinel.crier
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*

class PracticeGuideTest {
 private fun content()=javaClass.classLoader!!.getResourceAsStream("customer-practice.json")!!.bufferedReader().use { it.readText() }
 @Test fun bundledGuideHasThreeReadonlyPurposes() {
  val guide=PracticeGuide.parse(content())
  assertEquals(listOf("alerts","trade","follow"),guide.journeys.map { it.id })
  assertTrue(guide.format("alerts").contains("suppressed baseline"))
  assertTrue(guide.notice.contains("optional")); assertTrue(guide.privacy.contains("API keys"))
 }
 @Test fun permissionAndActionFieldsAreRejected() {
  val root=JSONObject(content()).put("enabled",true)
  assertTrue(runCatching { PracticeGuide.parse(root.toString()) }.isFailure)
  root.remove("enabled"); root.getJSONArray("journeys").getJSONObject(0).getJSONArray("steps").getJSONObject(0).put("action","submit")
  assertTrue(runCatching { PracticeGuide.parse(root.toString()) }.isFailure)
 }
 @Test fun badVersionAndDuplicatePurposeAreRejected() {
  val root=JSONObject(content()).put("version",true)
  assertTrue(runCatching { PracticeGuide.parse(root.toString()) }.isFailure)
  root.put("version",1).getJSONArray("journeys").getJSONObject(1).put("id","alerts")
  assertTrue(runCatching { PracticeGuide.parse(root.toString()) }.isFailure)
 }
}

package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test

class SetupChoicesTest {
 @Test fun friendlyChoicesRoundTripEveryProtocolValue() {
  val expected=listOf(SetupChoices.environment to listOf("paper","live"), SetupChoices.pricing to listOf("exact_limit","bounded_limit","market"), SetupChoices.format to listOf("card","plain"), SetupChoices.instrument to listOf("stock","option"))
  for((choices,values) in expected) {
   assertEquals(values,choices.options.map { it.value })
   for(value in values) {
    val selection=choices.forSaved(value)
    assertEquals(value,selection.requireValue(selection.selectedIndex))
    assertFalse(selection.labels[selection.selectedIndex].isBlank())
    assertNotEquals(value,selection.labels[selection.selectedIndex])
   }
  }
 }
 @Test fun unknownSavedValuesStaySelectedUntilUserChooses() {
  for(choices in listOf(SetupChoices.environment,SetupChoices.pricing,SetupChoices.format,SetupChoices.instrument)) {
   for(saved in listOf("", "future-mode", "MARKET", " paper ")) {
    val selection=choices.forSaved(saved)
    assertEquals(saved,selection.valueAt(selection.selectedIndex))
    assertTrue(selection.labels[selection.selectedIndex].contains("Choose"))
    try { selection.requireValue(selection.selectedIndex); fail("Unknown saved value accepted: $saved") } catch(expected:IllegalArgumentException) { }
    for((index,option) in choices.options.withIndex()) assertEquals(option.value,selection.requireValue(index+1))
   }
  }
 }
 @Test fun selectingAnOptionDoesNotChangeOtherSavedConfiguration() {
  val config=org.json.JSONObject("""{"environment":"future","mode":"unknown","maxQuantity":"bad-cap","age":10,"amount":"0.02","discordTemplate":"{action} {symbol}"}""")
  val before=config.toString()
  val selection=SetupChoices.environment.forSaved(config.getString("environment"))
  assertEquals("future",selection.valueAt(selection.selectedIndex))
  assertEquals(before,config.toString())
  config.put("environment",selection.requireValue(1))
  assertEquals("paper",config.getString("environment"))
  assertEquals("unknown",config.getString("mode"))
  assertEquals("bad-cap",config.getString("maxQuantity"))
  assertEquals("{action} {symbol}",config.getString("discordTemplate"))
 }
}

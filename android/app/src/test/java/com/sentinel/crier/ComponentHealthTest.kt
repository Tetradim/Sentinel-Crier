package com.sentinel.crier

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ComponentHealthTest {
 private class Memory { var raw=JSONObject(); fun ledger(clock:Clock)=ComponentHealth({JSONObject(raw.toString())},{raw=JSONObject(it.toString())},{clock.wall},{clock.mono}) }
 private class Clock { var wall=1000000L; var mono=1000L; fun advance(ms:Long) { wall+=ms; mono+=ms } }
 @Test fun restartAndReconnectPreserveHistoryButNotReadiness() {
  val clock=Clock(); val memory=Memory(); val h=memory.ledger(clock)
  val token=h.begin("a",setOf("broker")); h.record(token,"broker","healthy","verified")
  assertEquals("healthy",h.snapshot().first().state)
  assertEquals("stopped",memory.ledger(clock).snapshot().first().state)
  assertEquals(1000000L,memory.ledger(clock).snapshot().first().lastSuccess)
  val next=h.begin("a",setOf("broker")); assertEquals("waiting",h.snapshot().first().state)
  h.record(token,"broker","healthy","verified"); assertEquals("waiting",h.snapshot().first().state)
  h.record(next,"broker","healthy","verified"); h.stop(token)
  assertEquals("healthy",h.snapshot().first().state)
  h.stop(next); assertEquals("stopped",h.snapshot().first().state)
 }
 @Test fun scopeAndStoppedTicketsFenceLateCallbacks() {
  val h=Memory().ledger(Clock()); val a=h.begin("a",setOf("broker")); h.record(a,"broker","healthy","verified")
  val b=h.begin("b",setOf("broker")); assertNull(h.snapshot().first().lastSuccess)
  h.stop(b); h.record(b,"broker","healthy","verified"); assertEquals("stopped",h.snapshot().first().state)
  assertNull(h.snapshot().first().lastSuccess)
 }
 @Test fun monotonicAgeAndClockChangesNeverMakeOldEvidenceFresh() {
  val clock=Clock(); val h=Memory().ledger(clock); val t=h.begin("a",setOf("broker"))
  h.record(t,"broker","healthy","verified"); clock.advance(61000)
  assertEquals("stale",h.snapshot().first().state)
  clock.wall-=3600000; assertEquals("clock_changed",h.snapshot().first().state)
  assertEquals(61000L,h.snapshot().first().ageMillis)
 }
 @Test fun failuresAreVisibleAndHealthCannotThrowIntoTheTradingPath() {
  val h=ComponentHealth({JSONObject()},{error("storage unavailable")})
  val t=h.begin("a",setOf("broker")); h.record(t,"broker","healthy","verified")
  assertTrue(h.unavailable); assertEquals("healthy",h.snapshot().first().state)
  val corrupt=ComponentHealth({error("corrupt")},{fail("Do not overwrite unreadable history")})
  val next=corrupt.begin("b",setOf("broker")); corrupt.record(next,"broker","healthy","verified")
  assertTrue(corrupt.unavailable)
 }
 @Test fun fixedReasonsExcludeRawSecretsAndIdleIsNotSuccess() {
  val h=Memory().ledger(Clock()); val t=h.begin("a",setOf("discord"))
  h.record(t,"discord","idle","no_work")
  assertNull(h.snapshot().last().lastSuccess)
  try { h.record(t,"broker","blocked","Bearer private"); fail("Reject raw errors") } catch(_:IllegalArgumentException) {}
 }
 @Test fun scopeHashesCredentialsAndSeparatesDestinationsAndCustomerProjects() {
  val c=JSONObject().put("environment","paper").put("account","account").put("token","private-token").put("discordWebhook","private-destination")
  val a=ComponentHealth.scope(c,"alerts"); assertEquals(64,a.length); assertFalse(a.contains("private"))
  c.put("discordWebhook","other"); assertNotEquals(a,ComponentHealth.scope(c,"alerts"))
  val b=ComponentHealth.scope(c,"alerts"); c.put("oauthService","other-project"); assertNotEquals(b,ComponentHealth.scope(c,"alerts"))
 }
 @Test fun presentationIsExplicitAboutStoppedHistoryAndStorageFailure() {
  val h=Memory().ledger(Clock()); val t=h.begin("a",setOf("broker")); h.record(t,"broker","healthy","verified"); h.stop(t)
  val text=ComponentHealth.describe(h.snapshot(),true)
  assertTrue(text.contains("Broker account: stopped")); assertTrue(text.contains("Health history unavailable"))
  assertTrue(text.contains("do not resume monitoring")); assertTrue(text.contains("Last success (UTC)"))
 }
 @Test fun alertsAndTradingCanReportIndependentlyWithoutStoppingEachOther() {
  val h=Memory().ledger(Clock())
  val trade=h.begin("trade-account",setOf("broker"),"intent")
  val alerts=h.begin("alerts-account",setOf("broker"),"alerts")
  h.record(trade,"broker","healthy","verified"); h.stop(alerts)
  assertEquals("healthy",h.snapshot(h.context("intent")).first().state)
  assertEquals("stopped",h.snapshot(h.context("alerts")).first().state)
 }
}

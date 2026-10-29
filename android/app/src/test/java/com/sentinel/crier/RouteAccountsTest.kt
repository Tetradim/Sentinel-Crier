package com.sentinel.crier
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
class RouteAccountsTest {
 private fun config(account:String="one",environment:String="paper")=JSONObject().put("account",account).put("environment",environment)
 @Test fun durableOwnerBlocksAnotherRouteEvenAfterDisconnect() {
  val saved=listOf("owner" to config())
  RouteAccounts.requireAvailable("owner",config(),saved)
  try { RouteAccounts.requireAvailable("another",config(),saved); fail("Retained ownership must block reuse") } catch(_:IllegalArgumentException) {}
 }
 @Test fun accountsAndEnvironmentsHaveIndependentOwnership() {
  val saved=listOf("owner" to config())
  RouteAccounts.requireAvailable("second",config("two"),saved)
  RouteAccounts.requireAvailable("live",config(environment="live"),saved)
 }
 @Test fun unsupportedBrokerFailsClosed() {
  try { RouteAccounts.key(config().put("broker","webull")); fail("Unsupported adapter") } catch(_:IllegalArgumentException) {}
 }
 @Test fun independentGatesDoNotStopOtherRoutes() {
  val first=ExecutionStartGate(); val second=ExecutionStartGate(); val a=Any(); val b=Any()
  assertTrue(first.claim(first.reserve(),a,true)); assertTrue(second.claim(second.reserve(),b,true))
  first.stop(); assertFalse(first.permits(a)); assertTrue(second.permits(b))
  first.drained(a); assertFalse(first.active); assertTrue(second.active)
 }
 @Test fun legacyPathsRemainAndNewControlsAreScoped() {
  assertEquals("controls",RouteStorage.preferences("controls","legacy"))
  val a="11111111-1111-1111-1111-111111111111"; val b="22222222-2222-2222-2222-222222222222"
  assertNotEquals(RouteStorage.preferences("controls",a),RouteStorage.preferences("controls",b))
  assertEquals("vault",RouteStorage.preferences("vault",a))
  assertEquals("intent.db",Settings.journalName(JSONObject()))
 }
}

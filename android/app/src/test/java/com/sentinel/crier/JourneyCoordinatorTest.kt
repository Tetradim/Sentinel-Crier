package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test

class JourneyCoordinatorTest {
 private class Harness {
  val events=mutableListOf<String>()
  val journeys=JourneyCoordinator(
   saveNavigation={ events.add("navigation:$it") },
   invalidateCustomer={ events.add("invalidate-customer") },
   stopAlerts={ events.add("stop-alerts") },
   savePurpose={ events.add("purpose:$it") },
   retireRoute={ events.add("retire-route") },
   saveRoute={ events.add("route:$it") },
   recreate={ events.add("recreate") })
 }
 @Test fun purposeSelectionPersistsNavigationAndClearsProviderReadinessBeforeRecreation() {
  for((purpose,screen) in listOf("alerts" to "Account","trade" to "Trade","follow" to "Trade")) {
   val h=Harness(); h.journeys.choosePurpose(purpose)
   assertEquals(listOf("navigation:$screen","invalidate-customer","stop-alerts","purpose:$purpose","recreate"),h.events)
  }
 }
 @Test fun routeSwitchRetiresOldActivityBeforeResolvingAndSavingNewRoute() {
  val h=Harness()
  h.journeys.changeRoute { h.events.add("resolve-route"); "second" }
  assertEquals(listOf("stop-alerts","retire-route","resolve-route","route:second","recreate"),h.events)
 }
 @Test fun failedRouteCreationDoesNotPersistOrRecreate() {
  val h=Harness()
  try { h.journeys.changeRoute { error("cannot create") }; fail("should fail") } catch(_:IllegalStateException) { }
  assertEquals(listOf("stop-alerts","retire-route"),h.events)
 }
}

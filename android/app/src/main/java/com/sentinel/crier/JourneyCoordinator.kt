package com.sentinel.crier

/** Journey transitions only. Process workers, OAuth inbox, and Alerts ownership
 * remain with the Activity's existing owners; no transition enables execution.
 */
class JourneyCoordinator(
 private val saveNavigation:(String)->Unit,
 private val invalidateCustomer:()->Unit,
 private val stopAlerts:()->Unit,
 private val savePurpose:(String)->Unit,
 private val retireRoute:()->Unit,
 private val saveRoute:(String)->Unit,
 private val recreate:()->Unit
) {
 fun choosePurpose(purpose:String) {
  saveNavigation(if(purpose=="alerts") "Account" else "Trade")
  invalidateCustomer()
  stopAlerts()
  savePurpose(purpose)
  recreate()
 }

 /** Retire callbacks before creating/selecting the next route. Other routes'
  * Trade/Follow workers are independent and are never stopped here.
  */
 fun changeRoute(resolveRoute:()->String) {
  stopAlerts()
  retireRoute()
  saveRoute(resolveRoute())
  recreate()
 }
}

package com.sentinel.crier

import android.Manifest
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class BrokerageAcceptanceTest {
 @get:Rule val notifications=GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
 @Test fun nativeDisconnectedNavigationAndScreenshotsNeverStartWorkers() {
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   onView(withText("Home")).perform(click()); capture("android-home-disconnected")
   onView(withContentDescription("Stop all connections")).check(matches(isDisplayed()))
   onView(withText("Positions")).perform(click()); capture("android-positions-disconnected")
   onView(withText("Account")).perform(click()); capture("android-account-disconnected")
   onView(withText("Trade")).perform(click()); capture("android-trade-disconnected")
   onView(withContentDescription("Stop all connections")).check(matches(isDisplayed()))
   scenario.onActivity { assertFalse(SyncService.active) }
  }
 }
 @Test fun bankObservationDoesNotBlockMainThreadAndLateResultIsDiscarded() {
  val held=CountDownLatch(1); val release=CountDownLatch(1); val worker=Executors.newSingleThreadExecutor()
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   lateinit var bank:AccountBank; val config=JSONObject().put("account","synthetic-ui").put("environment","paper")
   scenario.onActivity { bank=AndroidAccountBank.bank(it) }
   val scope=RouteAccounts.key(config); bank.enable(scope,"100","100",emptyMap())
   val holder=Thread { bank.locked { held.countDown(); release.await(5,TimeUnit.SECONDS) } }; holder.start()
   assertTrue(held.await(2,TimeUnit.SECONDS)); var current=true
   try {
    val start=System.nanoTime()
    scenario.onActivity { activity -> AccountBankDialogs(activity,activity.routeId,config,worker,{current},{ fail(it) }).show() }
    assertTrue("Ledger observation must not wait for dispatch on main",TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start)<1000)
    scenario.onActivity { current=false }
   } finally { release.countDown(); holder.join(2000); worker.shutdown(); assertTrue(worker.awaitTermination(3,TimeUnit.SECONDS)) }
  }
 }
 @Test fun editingPoolsWhileWorkersActiveShowsGuidanceWithoutThrowing() {
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   scenario.onActivity { activity ->
    AccountBankDialogs(activity,activity.routeId,JSONObject(),java.util.concurrent.Executor { it.run() },{true},{},workersActive={true}).editPools()
   }
   onView(withText("Stop connections to edit pools")).check(matches(isDisplayed()))
   onView(withText("Close")).perform(click())
  }
 }
 private fun capture(name:String) {
  val instrumentation=InstrumentationRegistry.getInstrumentation(); instrumentation.waitForIdleSync()
  val bitmap=instrumentation.uiAutomation.takeScreenshot(); assertNotNull(bitmap)
  val bytes=java.io.ByteArrayOutputStream(); bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,bytes)
  val encoded=android.util.Base64.encodeToString(bytes.toByteArray(),android.util.Base64.NO_WRAP)
  encoded.chunked(3000).forEachIndexed { index,chunk -> android.util.Log.i("CrierScreenshots","CRIER_SCREENSHOT|$name|${index*3000}|$chunk") }
  bitmap.recycle()
 }
}

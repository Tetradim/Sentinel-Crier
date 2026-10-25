package com.sentinel.crier
import android.Manifest
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.rule.GrantPermissionRule
import org.hamcrest.CoreMatchers.containsString
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CustomerAcceptanceTest {
 @get:Rule val notifications:GrantPermissionRule=GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
 @Test fun optionalGuidesDoNotChoosePurposeOrStartWorkers() {
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   var original=""
   scenario.onActivity { original=it.getSharedPreferences("journey",0).getString("purpose","") ?: ""; assertFalse(SyncService.active) }
   for(title in listOf("Alerts only","Trade / share","Follow trades")) {
    onView(withText("Optional paper practice / support")).perform(scrollTo(),click())
    onView(withText(title)).perform(click())
    onView(withText(containsString("Paper practice is optional"))).check(matches(isDisplayed()))
    onView(withText("Return to setup")).perform(click())
   }
   scenario.onActivity { assertEquals(original,it.getSharedPreferences("journey",0).getString("purpose","")); assertFalse(SyncService.active) }
  }
 }
 @Test fun editableFieldsHaveNativeLabelAssociationsAndHints() {
  ActivityScenario.launch(MainActivity::class.java).use { scenario -> scenario.onActivity { activity ->
   val views=mutableListOf<View>()
   fun collect(view:View) { views.add(view); if(view is ViewGroup) for(i in 0 until view.childCount) collect(view.getChildAt(i)) }
   collect(activity.findViewById(android.R.id.content))
   val inputs=views.filterIsInstance<EditText>(); assertTrue(inputs.isNotEmpty())
   for(input in inputs) {
    assertNotEquals(View.NO_ID,input.id); assertFalse(input.hint.isNullOrBlank())
    assertTrue(views.filterIsInstance<TextView>().any { it!==input && it.labelFor==input.id && it.text.toString()==input.hint.toString() })
   }
  } }
 }
}

package com.sentinel.crier

import android.app.Activity
import android.graphics.Color
import android.view.View
import android.widget.*
import org.json.JSONObject

/** Navigation changes presentation only; existing controls retain all execution authority. */
class BrokerageShell(private val activity:Activity,config:JSONObject,
 private val onTrade:()->Unit,private val onAlerts:()->Unit,private val onHealth:()->Unit,
 private val onPositions:((String)->Unit)->Unit,private val onAccounts:()->Unit,private val onStop:()->Unit) {
 val workspace=LinearLayout(activity).apply { orientation=1; setPadding(dp(16),dp(12),dp(16),dp(24)) }
 private val root=LinearLayout(activity).apply { orientation=1; setBackgroundColor(bg) }
 private val scroll=ScrollView(activity).apply { isFillViewport=true; addView(workspace) }
 private val home=LinearLayout(activity).apply { orientation=1; setPadding(dp(20),dp(24),dp(20),dp(20)) }
 private val positions=TextView(activity).apply { textSize=16f; setTextColor(ink); setPadding(dp(20),dp(24),dp(20),dp(24)); setTextIsSelectable(true) }
 private val body=FrameLayout(activity)
 private val tabs=mutableMapOf<String,Button>()
 private var selected="Home"
 var tradeAnchor:View?=null
 init {
  // API 30+ explicitly lays out edge-to-edge, so only this root applies safe insets.
  // API 26-29 keeps platform decor fitting and must not add a second set of padding.
  if(android.os.Build.VERSION.SDK_INT>=30) {
   activity.window.setDecorFitsSystemWindows(false)
   root.setOnApplyWindowInsetsListener { view,insets ->
    val safe=insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout() or android.view.WindowInsets.Type.ime())
    view.setPadding(safe.left,safe.top,safe.right,safe.bottom)
    insets
   }
  }
  val header=LinearLayout(activity).apply { setPadding(dp(12),dp(8),dp(16),dp(8)); setBackgroundColor(surface) }
  header.addView(Button(activity).apply { text="CRIER / ${config.optString("account").takeIf { it.isNotBlank() }?.takeLast(4) ?: "Account"}"; contentDescription="Select connection / account"; isAllCaps=false; textSize=12f; minWidth=0; setPadding(0,0,dp(8),0); setTextColor(ink); setBackgroundColor(surface); minHeight=dp(48); setOnClickListener { onAccounts() } },LinearLayout.LayoutParams(0,-2,1f))
  header.addView(label(when(config.optString("environment")) { "live"->"LIVE"; "paper"->"PAPER"; else->"OFFLINE" },10f,accent).apply { gravity=17 },LinearLayout.LayoutParams(-2,dp(48)))
  header.addView(Button(activity).apply { text="Stop"; contentDescription="Stop all connections"; isAllCaps=false; minHeight=dp(48); setTextColor(Color.rgb(255,112,122)); setBackgroundColor(surface); setOnClickListener { onStop() } },LinearLayout.LayoutParams(dp(64),-2))
  root.addView(header); body.addView(scroll); body.addView(ScrollView(activity).apply { addView(home) }); body.addView(ScrollView(activity).apply { addView(positions) }); root.addView(body,LinearLayout.LayoutParams(-1,0,1f))
  val nav=LinearLayout(activity).apply { setBackgroundColor(surface) }
  for(name in listOf("Home","Trade","Positions","Account")) {
   val tab=Button(activity).apply { text=name; textSize=11f; isAllCaps=false; minHeight=dp(56); minWidth=0; minimumWidth=0; setPadding(0,dp(8),0,dp(8)); setSingleLine(true); setBackgroundColor(surface); setOnClickListener { if(name=="Trade") onTrade(); select(name) } }
   tabs[name]=tab; nav.addView(tab,LinearLayout.LayoutParams(0,-2,1f))
  }
  root.addView(nav); activity.setContentView(root); root.requestApplyInsets()
  home.addView(label("YOUR WORKSPACE",12f,muted))
  home.addView(label("Account overview",24f,ink).apply { setTypeface(null,1); setPadding(0,dp(12),0,dp(20)) })
  home.addView(label("${config.optString("role").ifBlank { "No connection selected" }} / ${config.optString("environment").ifBlank { "Choose an environment" }}",16f,ink))
  home.addView(label("Saved setup is not current broker verification. Reconnect explicitly to reconcile retained orders.",14f,muted).apply { setPadding(0,dp(12),0,dp(24)) })
  action("Open trade workspace") { onTrade(); select("Trade") }
  action("Broker-fill alerts",onAlerts); action("Connection health and recovery",onHealth)
  action("Account and connection setup") { select("Account") }; select("Home")
 }
 private fun dp(n:Int)=(n*activity.resources.displayMetrics.density).toInt()
 private fun label(value:String,size:Float,color:Int)=TextView(activity).apply { text=value; textSize=size; setTextColor(color) }
 private fun action(title:String,run:()->Unit) { home.addView(Button(activity).apply { text=title; isAllCaps=false; textSize=15f; minHeight=dp(52); setTextColor(ink); backgroundTintList=android.content.res.ColorStateList.valueOf(surface); setOnClickListener { run() } },LinearLayout.LayoutParams(-1,-2).apply { bottomMargin=dp(8) }) }
 fun select(name:String) {
  selected=name
  for(i in 0 until body.childCount) body.getChildAt(i).visibility=if(i==when(name) { "Home"->1; "Positions"->2; else->0 }) View.VISIBLE else View.GONE
  tabs.forEach { (title,view) -> view.setTextColor(if(title==name) accent else muted); view.isSelected=title==name }
  if(name=="Positions") { positions.text="Loading retained positions..."; onPositions { if(selected=="Positions") positions.text=it } }
  if(name=="Trade") scroll.post { tradeAnchor?.let { scroll.scrollTo(0,it.top) } }
  if(name=="Account") scroll.post { scroll.scrollTo(0,0) }
 }
 fun styleWorkspace()=style(workspace)
 private fun style(view:View) {
  if(view is TextView) { view.setTextColor(ink); if(view !is Button && view !is EditText) view.setPadding(0,dp(6),0,dp(6)) }
  if(view is Button) { view.isAllCaps=false; view.minHeight=dp(48); view.textSize=14f; view.backgroundTintList=android.content.res.ColorStateList.valueOf(surface) }
  if(view is EditText) { view.minHeight=dp(48); view.setHintTextColor(muted); view.backgroundTintList=android.content.res.ColorStateList.valueOf(accent) }
  if(view is android.view.ViewGroup) for(i in 0 until view.childCount) style(view.getChildAt(i))
 }
 companion object { val bg=Color.rgb(12,16,23); val surface=Color.rgb(24,31,42); val ink=Color.rgb(235,240,248); val muted=Color.rgb(159,173,193); val accent=Color.rgb(64,165,255) }
}

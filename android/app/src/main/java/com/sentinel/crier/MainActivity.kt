package com.sentinel.crier
import android.app.Activity
import android.os.Bundle
import android.content.Intent
import android.text.InputType
import android.widget.*
import org.json.JSONObject
import java.net.URI
import java.util.concurrent.Executors
class MainActivity:Activity() {
 private companion object {
  // One process-owned writer survives Activity recreation and in-flight acknowledgements.
  val sharedIo=Executors.newSingleThreadExecutor()
  val alertsOwner=AlertsSessionOwner()
  var customer:CustomerOAuth?=null
  var redeemed:JSONObject?=null
  val returnInbox=OAuthReturnInbox()
 }
 private val io=sharedIo
 private var pendingExport:String?=null
 private var journey=""
 private var oauthConnection:JSONObject?=null
 private var guided:GuidedAlerts?=null
 private val alertsTimer=android.os.Handler(android.os.Looper.getMainLooper())
 @Volatile private var foreground=false
 @Volatile private var lifecycleRevision=0L
 private var alertsPolling=false
 private val alertsTick=object:Runnable { override fun run() { val g=guided; if(g?.isEnabled()==true && !alertsPolling) { alertsPolling=true; background { try { g.tick(); g.evidence } finally { runOnUiThread { alertsPolling=false } } } }; alertsTimer.postDelayed(this,10000) } }
 private lateinit var panel:LinearLayout
 private lateinit var status:TextView
 private lateinit var journal:Journal
 private inner class ChoicePicker(private val label:String, private val choices:SetupChoiceSet, saved:String) {
  val view=Spinner(this@MainActivity)
  private lateinit var selection:SetupSelection
  init { panel.addView(TextView(this@MainActivity).apply { text=label }); panel.addView(view); select(saved) }
  fun select(value:String) { selection=choices.forSaved(value); view.adapter=ArrayAdapter(this@MainActivity,android.R.layout.simple_spinner_item,selection.labels).apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }; view.setSelection(selection.selectedIndex) }
  fun value():String { try { return selection.requireValue(view.selectedItemPosition) } catch(e:IllegalArgumentException) { throw IllegalArgumentException("$label: choose a valid option") } }
  fun label():String=selection.labels[view.selectedItemPosition]
 }
 private fun advanced(title:String,build:()->Unit) {
  val parent=panel
  val contents=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; visibility=android.view.View.GONE }
  val toggle=Button(this).apply { text="$title · Show"; setOnClickListener { val show=contents.visibility!=android.view.View.VISIBLE; contents.visibility=if(show) android.view.View.VISIBLE else android.view.View.GONE; text="$title · ${if(show) "Hide" else "Show"}" } }
  parent.addView(toggle); parent.addView(contents)
  panel=contents
  try { build() } finally { panel=parent }
 }
 private fun field(label:String,value:String="",secret:Boolean=false):EditText { panel.addView(TextView(this).apply { text=label }); return EditText(this).apply { setText(value); if(secret) inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; panel.addView(this) } }
 private fun button(label:String,action:()->Unit):Button = Button(this).apply { text=label; setOnClickListener { try { action() } catch(e:Exception) { status.text=e.message } }; panel.addView(this) }
 private fun background(action:()->String) { val lifecycle=lifecycleRevision; val setupRevision=guided?.revision(); io.submit { if(isDestroyed || (guided!=null && (!foreground || lifecycle!=lifecycleRevision || setupRevision!=guided?.revision()))) { runOnUiThread { alertsPolling=false }; return@submit }; val message=try { action() } catch(e:Exception) { e.message ?: "Operation failed" }; runOnUiThread { status.text=message } } }
 override fun onCreate(state:Bundle?) {
  super.onCreate(state); journal=Journal(this)
  if(android.os.Build.VERSION.SDK_INT>=33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED) requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS),42)
  panel=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(32,32,32,32) }
  setContentView(ScrollView(this).apply { addView(panel) })
  panel.addView(TextView(this).apply { text="Crier · native intent mirroring"; textSize=24f })
  panel.addView(TextView(this).apply { text="Keep Crier running for mirroring. Android can suspend or stop background syncing; reopen to reconcile and resume. A running worker does not establish current broker or connection health." })
  status=TextView(this).apply { text="${if(Vault(this@MainActivity).read().has("account")) "Saved setup; reconnect and reconcile before new work. Current connection health is not verified here." else "Connection not ready. Choose Host or Receive, then save and verify your account."}\n${journal.meta("status").ifBlank { "Paused until enabled. Use paper credentials for testing." }}"; panel.addView(this) }
  customerSetup()
  handleOAuthReturn(intent?.dataString)
  journey=getSharedPreferences("journey",MODE_PRIVATE).getString("purpose","") ?: ""
  button("Alerts · publish my broker fills to Discord") { chooseJourney("alerts") }
  button("Trade / share · place and mirror orders") { chooseJourney("trade") }
  button("Follow · receive a trader’s orders") { chooseJourney("follow") }
  if(journey=="alerts") { alertsSetup(); return }
  if(journey.isBlank()) { status.text="Choose Alerts, Trade / share, or Follow. No connection or delivery starts from this screen."; return }
  panel.addView(TextView(this).apply { text=if(journey=="follow") "Follow: join by invitation, verify your own account, then explicitly enable execution. Recovery tools remain below." else "Trade / share: Host a connection, verify your account, then explicitly enable execution. Discord sharing is optional." })
  val old=Vault(this).read()
  var candidate=JSONObject(old.toString())
  var newConnection=false
  val environment=ChoicePicker("Account environment",SetupChoices.environment,old.optString("environment","paper"))
  lateinit var service:EditText
  advanced("Advanced · connection service") { service=field("Connection service HTTPS URL",old.optString("url",QuickConnection.defaultOrigin(this))) }
  val invitation=field("Receiver invitation link or 16-character code","",true)
  val key=field("Your Alpaca API key",old.optString("key"),true); val secret=field("Your Alpaca secret",old.optString("secret"),true)
  val mode=ChoicePicker("Order pricing",SetupChoices.pricing,old.optString("mode","exact_limit"))
  lateinit var bps:EditText; lateinit var amount:EditText; lateinit var age:EditText; lateinit var max:EditText
  val limits=TextView(this).apply { panel.addView(this) }
  fun updateLimits() { limits.text="Pricing: ${mode.label()}. Maximum entry quantity: ${max.text} (allowed 1–1000). Entry age: ${age.text}s. Slippage: ${bps.text} bps / $${amount.text} for bounded limits. Limits do not guarantee fills." }
  advanced("Advanced · execution limits") {
   bps=field("Maximum slippage basis points",old.optString("bps","100")); amount=field("Maximum slippage dollars",old.optString("amount","0.02"))
   age=field("Maximum entry age seconds (1–30)",old.optString("age","10")); max=field("Maximum quantity (1–1000)",old.optString("maxQuantity","1000"))
  }
  updateLimits()
  mode.view.onItemSelectedListener=object:AdapterView.OnItemSelectedListener { override fun onItemSelected(parent:AdapterView<*>?,view:android.view.View?,position:Int,id:Long) { updateLimits() }; override fun onNothingSelected(parent:AdapterView<*>?) {} }
  for(input in listOf(bps,amount,age,max)) input.addTextChangedListener(object:android.text.TextWatcher { override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int) {}; override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int) { updateLimits() }; override fun afterTextChanged(s:android.text.Editable?) {} })
  val live=CheckBox(this).apply { text="I authorize LIVE account trading if environment is live"; panel.addView(this) }
  val market=CheckBox(this).apply { text="I explicitly enable market orders (price is not bounded)"; isChecked=old.optString("mode")=="market"; panel.addView(this) }
  val separateAccount=CheckBox(this).apply { text="Save a different account in a separate journal on this connection. Restore the old profile to manage its outstanding orders."; panel.addView(this) }
  fun requireStopped() { require(!SyncService.active) { "Tap Stop workers for settings/recovery, then wait for stopped status." } }
  button("Stop workers for settings / recovery") {
   getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()
   SyncService.stopRequests(); stopService(Intent(this,SyncService::class.java))
   background { val deadline=System.currentTimeMillis()+45000; while(SyncService.active && System.currentTimeMillis()<deadline) Thread.sleep(100); requireStopped(); "Workers stopped. Credentials and connections can be changed; all journals retained." }
  }
  button("Host · create a new connection") {
   requireStopped(); val env=environment.value(); require(env in setOf("paper","live")); require(env!="live" || live.isChecked) { "Explicit live authorization required" }; val url=service.text.toString()
   background { candidate=QuickConnection.host(url,env); oauthConnection=JSONObject(candidate.toString()); newConnection=true; "Host connection created. Save and verify account, then create a receiver invitation." }
  }
  button("Receive · join by invitation") {
   requireStopped(); val env=environment.value(); require(env in setOf("paper","live")); require(env!="live" || live.isChecked) { "Explicit live authorization required" }; val invite=QuickConnection.invitation(invitation.text.toString(),service.text.toString())
   background { candidate=QuickConnection.receive(invite,env); oauthConnection=JSONObject(candidate.toString()); newConnection=true; "Receiver connected. Save and verify your own account to finish setup." }
  }
  button("Save and verify account / rotate broker credentials") {
   requireStopped(); val c=if(newConnection) JSONObject(candidate.toString()) else Vault(this).read(); require(c.has("token")) { "Host or Receive first" }
   require(c.getString("environment")==environment.value()) { "Environment changes need a new connection" }
   require(c.getString("environment")!="live" || live.isChecked) { "Explicit live authorization required" }
   val pricing=mode.value(); require(pricing in setOf("exact_limit","market","bounded_limit")); require(pricing!="market" || market.isChecked)
   require(age.text.toString().toInt() in 1..30 && max.text.toString().toInt() in 1..1000)
   c.apply { remove("bearer"); remove("oauthOwner"); remove("oauthService"); remove("oauthPurpose"); put("authMode","api_key") }.put("key",key.text.toString()).put("secret",secret.text.toString()).put("mode",pricing).put("bps",bps.text.toString().toInt()).put("amount",amount.text.toString()).put("age",age.text.toString().toInt()).put("maxQuantity",max.text.toString().toInt())
   Policy.price("1",pricing,false,c.getInt("bps"),c.getString("amount"))
   val createProfile=newConnection || separateAccount.isChecked
   background {
    c.put("account",Broker(c).account())
    synchronized(SyncService::class.java) { requireStopped(); Vault(this).save(c,createProfile) }
    newConnection=false; candidate=JSONObject(c.toString()); journal=Journal(this)
    "Saved ${c.getString("environment")} ${c.getString("role")}. Journal retained. Enable execution to reconcile and start."
   }
  }
  button("Restore a saved connection / account journal") {
   requireStopped(); val profiles=Vault(this).profiles()
   android.app.AlertDialog.Builder(this).setTitle("Saved connections · journals are retained").setItems(profiles.map { val c=it.getJSONObject("config"); "${c.optString("environment")} ${c.optString("role")} · account ${c.optString("account").take(8)} · ${it.getString("id").take(8)}" }.toTypedArray()) { _,index ->
    try { requireStopped(); Vault(this).select(profiles[index].getString("id")); recreate() } catch(e:Exception) { status.text=e.message }
   }.show()
  }
  button("Create and share receiver invitation (expires in 10 minutes)") {
   val c=Vault(this).read(); require(c.optString("role")=="host") { "Only a saved Host creates invitations" }
   background { val link=QuickConnection.invite(c); runOnUiThread { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { type="text/plain"; putExtra(Intent.EXTRA_TEXT,link) },"Share receiver invitation")) }; "Invitation ready; single use, expires in 10 minutes." }
  }
  button("Receivers · review and revoke") {
   val c=Vault(this).read(); require(c.optString("role")=="host") { "Only the host can revoke receivers" }
   background { val list=QuickConnection.receivers(c); runOnUiThread {
    android.app.AlertDialog.Builder(this).setTitle("Tap receiver to revoke access").setItems((0 until list.length()).map { val r=list.getJSONObject(it); "${r.getString("id")} · ${if(r.optInt("revoked")==1) "revoked" else "active"}" }.toTypedArray()) { _,i -> val r=list.getJSONObject(i)
     android.app.AlertDialog.Builder(this).setTitle("Revoke receiver?").setMessage("Stops future relay access. Orders already submitted remain at the receiver's broker and must be inspected there.").setPositiveButton("Revoke") { _,_ -> background { QuickConnection.revoke(c,r.getString("id")); "Receiver revoked" } }.setNegativeButton("Cancel",null).show()
    }.show()
   }; "${list.length()} receiver records" }
  }
  button("Enable execution / Follow / reconnect") { require(!SyncService.authClosing) { "Wait for sign out to finish" }; require(Vault(this).read().has("account")) { "Connection not ready. Choose Host or Receive, then save and verify your account." }; getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",false).putBoolean("enabled",true).commit(); if(!SyncService.active) SyncService.requestStart(this); status.text="Reconnecting; broker orders are reconciled before new work" }
  button("Pause new entries (cancel/exit stay active)") { getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).commit(); status.text="New entries paused; exits and cancellation remain active" }
  discordSettings(old)
  button("Unresolved orders and recovery status") { android.app.AlertDialog.Builder(this).setTitle("Execution and connection recovery").setMessage("${journal.meta("visibility")}\n${journal.meta("service")}\n${journal.meta("connection")}\n${journal.meta("status")}\n${journal.meta("protocolStatus")}\n${journal.unresolved()}\nRetain this journal. Never clear app data to resolve an unknown broker outcome.").setPositiveButton("Close",null).show() }
  if(journey=="trade") {
  panel.addView(TextView(this).apply { text="Host order entry · buy to open"; textSize=20f })
  val symbol=field("Symbol (stock or canonical OCC)"); val asset=ChoicePicker("Instrument",SetupChoices.instrument,"stock"); val qty=field("Quantity","1"); val price=field("Source limit price","1.00"); val trade=field("Trade UUID (filled automatically on enter)",journal.meta("lastTrade"))
  button("Select a journaled trade") { val records=journal.history(); android.app.AlertDialog.Builder(this).setTitle("Trade history").setItems(records.map { "${it.getString("symbol")} · ${it.getString("action")} · ${it.getString("trade_id").take(8)}" }.toTypedArray()) { _, index -> val selected=records[index]; symbol.setText(selected.getString("symbol")); asset.select(selected.getString("asset")); qty.setText(selected.getInt("quantity").toString()); price.setText(selected.getString("limit_price")); trade.setText(selected.getString("trade_id")) }.show() }
  for(action in listOf("enter","replace","cancel","exit")) button(action.replaceFirstChar { it.uppercase() }) {
   val c=Vault(this).read(); require(c.getString("role")=="host") { "Only host creates intents" }
   require(action !in setOf("enter","replace") || !getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) { "Enable execution first" }
   val e=if(action=="enter") journal.create(action,symbol.text.toString().trim().uppercase(),asset.value(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment")) else journal.create(action,symbol.text.toString().trim().uppercase(),asset.value(),qty.text.toString().toInt(),price.text.toString(),c.getString("environment"),trade.text.toString())
   trade.setText(e.getString("trade_id")); journal.setMeta("lastTrade",e.getString("trade_id")); if(!SyncService.active) SyncService.requestStart(this); status.text="Journaled $action; broker and relay dispatch independently"
  }
  }
  button("Diagnostics · timeline, premiums and latency") { val records=Diagnostics.export(journal); android.app.AlertDialog.Builder(this).setTitle("Execution diagnostics").setItems((0 until records.length()).map { val e=records.getJSONObject(it).getJSONObject("event"); "${e.getString("symbol")} ${e.getString("action")} · ${e.getString("event_id").take(8)}" }.toTypedArray()) { _, i -> android.app.AlertDialog.Builder(this).setTitle("Event evidence").setMessage(Diagnostics.describe(records.getJSONObject(i))).setPositiveButton("Close",null).show() }.show() }
  button("Share diagnostics JSON") { shareDiagnostics(false) }
  button("Share diagnostics CSV") { shareDiagnostics(true) }
  button("Save diagnostics JSON file") { saveDiagnostics(false) }
  button("Save diagnostics CSV file") { saveDiagnostics(true) }
  button("Refresh journal status") { status.text="${if(SyncService.active) "Workers active" else "Workers stopped / suspended"} · ${if(getSharedPreferences("controls",MODE_PRIVATE).getBoolean("paused",true)) "entries paused" else "entries enabled"}\n${journal.meta("visibility")}\n${journal.meta("service")}\n${journal.meta("connection")}\n${journal.meta("status")}\n${journal.meta("protocolStatus")}\n${journal.summary()}\nDiscord: ${journal.alertSummary()} ${journal.meta("discordStatus")}" }
  panel.addView(TextView(this).apply { text="Keep Crier running for mirroring. Android may stop background data sync; reopen to resume. Unknown broker outcomes remain blocked until reconciled. Cancel stops the unfilled remainder; Exit closes only this trade's acquired holdings." })
 }
 private fun customerClient():CustomerOAuth {
  val existing=customer
  if(existing!=null) return existing
  return CustomerOAuth(CustomerOAuth.sibling(QuickConnection.defaultOrigin(this)),EncryptedCustomerSessions(applicationContext),disconnected={ !SyncService.active && !alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.isEnabled() }).also { customer=it }
 }
 private fun requireCustomerCredentials(config:JSONObject) {
  val c=customerClient(); val session=EncryptedCustomerSessions(applicationContext).read()
  if(config.optString("authMode")=="oauth" || config.has("discordOAuthOwner") || config.has("discordOAuthService")) require(session.optString("service")==c.base) { "Sign in with the saved customer service" }
  if(config.optString("authMode")=="oauth") require(OAuthProvenance.matches(config,c.owner(),c.base)) { "Brokerage belongs to another customer service" }
  if(config.has("discordOAuthOwner") || config.has("discordOAuthService")) require(OAuthProvenance.matches(config,c.owner(),c.base,"discordOAuth")) { "Destination belongs to another customer service" }
 }
 private fun customerSetup() {
  advanced("Customer sign in · provider connections") {
   panel.addView(TextView(this).apply { text="Availability is verified before sign in. Use your Crier customer email and password. Provider consent opens in your browser, which must sign in as the same customer. Brokerage passwords are never requested." })
   val email=field("Crier customer email")
   val password=field("Crier customer password","",true)
   val environment=ChoicePicker("Provider account environment",SetupChoices.environment,"paper")
   val separate=CheckBox(this).apply { text="Create separate saved account journal (Trade / Follow only)"; panel.addView(this) }
   val gated=mutableListOf<Pair<Button,String?>>()
   fun gatedButton(label:String,provider:String?=null,action:()->Unit) { gated.add(button(label,action).apply { isEnabled=false } to provider) }
   button("Check customer service availability") { gated.forEach { it.first.isEnabled=false }; background { val c=customerClient(); val providers=c.capabilities(); runOnUiThread { if(!isDestroyed) gated.forEach { (b,p) -> b.isEnabled=if(p==null) providers.isNotEmpty() else p in providers } }; "Available provider connections: ${providers.joinToString()}. ${if(c.owner().isBlank()) "Sign in next" else "Customer session saved"}" } }
   fun login(signup:Boolean) { val e=email.text.toString(); val p=password.text.toString(); password.setText(""); background { val c=customerClient(); redeemed=null; if(c.login(e,p,signup)) "Signed in. Choose a provider connection." else "Check your email to confirm this Crier account, then sign in." } }
   gatedButton("Sign in to Crier") { login(false) }
   gatedButton("Create Crier customer account") { login(true) }
   button("Refresh customer session explicitly") { background { redeemed=null; customerClient().refresh(); "Customer session refreshed; begin authorization again." } }
   fun begin(provider:String) { val purpose=if(provider=="discord" || journey=="alerts") "alerts" else "trade"; val env=environment.value(); background { redeemed=null; val launch=customerClient().begin(provider,purpose,env); runOnUiThread { if(!isDestroyed) startActivity(Intent(Intent.ACTION_VIEW,android.net.Uri.parse(launch))) }; "Complete consent in your browser, then return here." } }
   gatedButton("Connect Alpaca in browser","alpaca") { begin("alpaca") }
   gatedButton("Connect Discord in browser","discord") { begin("discord") }
   button("Cancel pending provider connection") { background { redeemed=null; customerClient().cancel(); "Pending connection cancelled" } }
   button("Install returned provider connection · keep stopped") {
    getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()
    val create=separate.isChecked; val installLifecycle=lifecycleRevision
    background {
     val c=customerClient(); val grant=redeemed ?: error("Complete provider consent in this app process first")
     require(grant.getString("oauthOwner")==c.owner() && grant.getString("oauthService")==c.base) { "Customer changed; authorize again" }
     require(!SyncService.active && guided?.isEnabled()!=true) { "Stop all workers and Alerts before installing" }
     val alerts=journey=="alerts"
     val old=if(alerts) alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.saved() else oauthConnection ?: Vault(this).read()
     if(grant.getString("provider")=="alpaca") {
      require(grant.getString("purpose")==if(alerts) "alerts" else "trade") { "Authorization purpose differs from this setup" }
      val installed=OAuthInstall.broker(old,grant,c.owner(),true,create && !alerts) { value -> if(alerts) AlpacaFillReader(value).account() else Broker(value).account() }
      synchronized(SyncService::class.java) {
       require(!SyncService.active && foreground && installLifecycle==lifecycleRevision) { "Screen changed; install again" }
       if(alerts) alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.verify(installed)
       else { require(installed.has("token")) { "Host or Receive first" }; Vault(this).save(installed,create || oauthConnection!=null); oauthConnection=null; journal=Journal(this) }
      }
     } else {
      require(old.has("account")) { "Verify and save a brokerage account first" }
      require((!old.has("discordOAuthOwner") && !old.has("discordOAuthService")) || OAuthProvenance.matches(old,c.owner(),c.base,"discordOAuth")) { "Saved destination belongs to another customer" }
      require(old.optString("authMode")!="oauth" || OAuthProvenance.matches(old,c.owner(),c.base)) { "Saved connection belongs to another customer" }
      val next=JSONObject(old.toString()).put("discordWebhook",grant.getString("credential")).put("discordOAuthOwner",c.owner()).put("discordOAuthService",c.base).put("discordGuild",grant.getString("guild_id")).put("discordChannel",grant.getString("channel_id"))
      if(alerts) { require(foreground && installLifecycle==lifecycleRevision) { "Screen changed; install again" }; alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.verify(next) }
      else synchronized(SyncService::class.java) { require(!SyncService.active && foreground && installLifecycle==lifecycleRevision); require(next.optString("discordWebhook")==old.optString("discordWebhook") || !journal.hasUndeliveredAlerts()) { "Inspect and close queued or uncertain Discord messages before changing destination" }; Vault(this).save(next) }
     }
     redeemed=null; runOnUiThread { if(!isDestroyed) { Toast.makeText(this,"Provider installed; verify and enable explicitly",Toast.LENGTH_LONG).show(); recreate() } }; "Provider connection installed encrypted. Workers remain stopped; verify, preview and enable explicitly."
    }
   }
   button("Sign out · stop workers and forget provider tokens") {
    SyncService.beginAuthStop()
    guided?.stop(); alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.stop()
    getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()
    SyncService.stopRequests(); stopService(Intent(this,SyncService::class.java))
    io.submit {
     val message=try {
      val deadline=System.currentTimeMillis()+45000
      while(SyncService.active && System.currentTimeMillis()<deadline) Thread.sleep(100)
      require(!SyncService.active) { "Workers still stopping; sign out again when stopped" }
      synchronized(SyncService::class.java) { require(!SyncService.active); redeemed=null; returnInbox.clear(); customerClient().invalidate(); Vault(this).forgetOAuthCredentials(); alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }.forgetOAuth(); customerClient().logout(); getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit(); SyncService.finishAuthStop() }
      runOnUiThread { if(!isDestroyed) { Toast.makeText(this,"Signed out; journals and evidence retained",Toast.LENGTH_LONG).show(); recreate() } }
      "Signed out. Tokens forgotten; orders, journals and message evidence retained."
     } catch(_:Exception) { "Sign out incomplete. Stop workers and try again; evidence retained." }
     runOnUiThread { if(!isDestroyed) status.text=message }
    }
   }
  }
 }
 private fun handleOAuthReturn(raw:String?) {
  if(raw==null) return
  intent?.data=null
  returnInbox.enqueue(raw)
  dispatchOAuthReturn()
 }
 private fun dispatchOAuthReturn() {
  val revision=lifecycleRevision
  io.submit {
   val raw=returnInbox.take(foreground && revision==lifecycleRevision) ?: return@submit
   val message=try { redeemed=customerClient().complete(raw); "Provider returned. Review your setup, stop workers, then tap Install returned provider connection." } catch(_:Exception) { "Provider return rejected or unavailable. Start a new authorization in this app process." }
   runOnUiThread { if(!isDestroyed) status.text=message }
  }
 }
 override fun onNewIntent(value:Intent) { super.onNewIntent(value); intent=value; handleOAuthReturn(value.dataString) }
 private fun chooseJourney(value:String) {
  customer?.invalidate(); redeemed=null; returnInbox.clear()
  guided?.stop()
  getSharedPreferences("journey",MODE_PRIVATE).edit().putString("purpose",value).commit()
  recreate()
 }
 private fun alertsSetup() {
  val g=alertsOwner.get { GuidedAlerts(EncryptedAlertsDocument(applicationContext)) }; guided=g
  val saved=g.saved()
  status.text="Alerts only · saved settings are not current verification. No orders are created. Any previously enabled Trade/Follow workers are independent; stop them using the control below."
  panel.addView(TextView(this).apply { text="""1 · Verify read access. No Host, Receive or relay is required.
2 · Preview a labelled synthetic message.
3 · Optionally send a test, then explicitly enable broker-fill delivery.
Monitoring runs only while this screen is foreground. Leaving pauses monitoring and clears readiness; return, verify, preview and enable to resume the retained cursor. First enable starts now; earlier fills are not replayed. Android background delivery is not provided by this journey.""" })
  button("Stop existing Trade / Follow workers") {
   getSharedPreferences("controls",MODE_PRIVATE).edit().putBoolean("paused",true).putBoolean("enabled",false).commit()
   SyncService.stopRequests(); stopService(Intent(this,SyncService::class.java)); status.text="Trade / Follow stop requested; its journals are retained."
  }
  val env=ChoicePicker("Alerts account environment",SetupChoices.environment,saved.optString("environment","paper"))
  val key=field("Alpaca API key · read access",saved.optString("key"),true)
  val secret=field("Alpaca secret",saved.optString("secret"),true)
  val webhook=field("Discord webhook URL · encrypted",saved.optString("discordWebhook"),true)
  val format=ChoicePicker("Alerts message format",SetupChoices.format,saved.optString("discordStyle","card"))
  val template=field("Message template",saved.optString("discordTemplate","{action} {symbol}"))
  fun input():JSONObject { val saved=g.saved(); if(key.text.toString().isBlank() && secret.text.toString().isBlank() && saved.optString("authMode")=="oauth") { require(OAuthProvenance.matches(saved,customerClient().owner(),customerClient().base) && saved.getString("environment")==env.value()); return JSONObject(saved.toString()).put("discordWebhook",webhook.text.toString().trim()).put("discordStyle",format.value()).put("discordTemplate",template.text.toString()) }; return OAuthProvenance.preserveDestination(saved,JSONObject().put("environment",env.value()).put("key",key.text.toString().trim()).put("secret",secret.text.toString().trim()).put("discordWebhook",webhook.text.toString().trim()).put("discordStyle",format.value()).put("discordTemplate",template.text.toString()))
  }
  val changed=object:android.text.TextWatcher { override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int) {}; override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int) { g.invalidate(); status.text=g.evidence }; override fun afterTextChanged(s:android.text.Editable?) {} }
  listOf(key,secret,webhook,template).forEach { it.addTextChangedListener(changed) }
  val pickerChanged=object:AdapterView.OnItemSelectedListener { override fun onItemSelected(parent:AdapterView<*>?,view:android.view.View?,position:Int,id:Long) { g.invalidate() }; override fun onNothingSelected(parent:AdapterView<*>?) {} }
  env.view.onItemSelectedListener=pickerChanged; format.view.onItemSelectedListener=pickerChanged
  button("1 · Save and verify Alerts account") { val c=input(); background { g.verify(c); g.evidence } }
  button("2 · Preview synthetic Discord message") { android.app.AlertDialog.Builder(this).setTitle("TEST MESSAGE · no trade or fill").setMessage(g.preview()).setPositiveButton("Close",null).show() }
  button("3 · Send one synthetic test (optional)") { background { g.test() } }
  button("Enable real broker-fill alerts in foreground") { background { g.enable(); g.evidence } }
  button("Stop Alerts and clear readiness") { g.stop(); status.text=g.evidence }
  button("Alerts readiness and delivery history") { background { "${g.evidence}\n${g.testEvidence}\n${g.history()}" } }
  button("Close inspected undelivered messages") {
   android.app.AlertDialog.Builder(this).setTitle("Close without retrying?").setMessage("Inspect Discord first: an uncertain message may already exist. Closing prevents retries and retains delivery evidence. Stop monitoring first. No automatic uncertain retry is performed.").setPositiveButton("Inspected · close messages") { _,_ -> background { g.closeInspected(); g.history() } }.setNegativeButton("Cancel",null).show()
  }
  button("View retained Trade / Follow recovery") { android.app.AlertDialog.Builder(this).setTitle("Trade / Follow recovery · independent journal").setMessage("${journal.meta("service")}\n${journal.meta("status")}\n${journal.unresolved()}\nChoose Trade or Follow to manage this journal. Alerts controls never reconcile or submit orders.").setPositiveButton("Close",null).show() }
  alertsTimer.postDelayed(alertsTick,10000)
 }
 private fun discordSettings(old:JSONObject) {
  panel.addView(TextView(this).apply { text="Discord alerts"; textSize=20f })
  val webhook=field("Discord webhook URL (stored encrypted)",old.optString("discordWebhook"),true)
  val style=ChoicePicker("Message format",SetupChoices.format,old.optString("discordStyle","card"))
  lateinit var template:EditText
  advanced("Advanced · message template") { template=field("Template: {action} {symbol}; fields: symbol, action, quantity, price, status, trade_id",old.optString("discordTemplate","{action} {symbol}")) }
  val selections=Discord.fields.associateWith { name -> CheckBox(this).apply { text="Show $name"; isChecked=name in old.optString("discordFields",Discord.fields.joinToString(",")).split(','); panel.addView(this) } }
  fun settings():JSONObject { val c=Vault(this).read(); c.put("discordWebhook",if(webhook.text.toString().isBlank()) "" else Discord.destination(webhook.text.toString())); require(style.value() in setOf("card","plain")); c.put("discordStyle",style.value()).put("discordTemplate",template.text.toString()).put("discordFields",selections.filterValues { it.isChecked }.keys.joinToString(",")); Discord.preview(c); return c }
  button("Preview Discord message") { android.app.AlertDialog.Builder(this).setTitle("Preview · TEST provenance").setMessage(Discord.readablePreview(settings())).setPositiveButton("Close",null).show() }
  button("Save Discord destination and template") { require(!SyncService.active) { "Stop workers to apply settings safely" }; val c=settings(); require(c.has("account")) { "Verify account first" }; require(c.optString("discordWebhook")==Vault(this).read().optString("discordWebhook") || !journal.hasUndeliveredAlerts()) { "Queued alerts belong to the current destination. Deliver or explicitly discard them before changing it." }; Vault(this).save(c); status.text="Discord settings saved. Reconnect to resume delivery." }
  button("Queue test message") { requireCustomerCredentials(Vault(this).read()); require(Vault(this).read().optString("discordWebhook").isNotBlank()) { "Save a Discord destination first" }; val id=Discord.test(journal); background { Discord.deliver(journal,Vault(this).read(),jobId=id); "Discord: ${journal.alertSummary()} · ${journal.meta("discordStatus")}" } }
  button("Retry Discord deliveries") { requireCustomerCredentials(Vault(this).read()); require(!SyncService.active) { "Stop workers before inspecting and retrying uncertain deliveries" }; android.app.AlertDialog.Builder(this).setTitle("Retry deliveries?").setMessage("Some messages may already exist in Discord after a lost acknowledgement. Inspect the channel first. Retrying uncertain messages can create duplicates.").setPositiveButton("Retry; accept duplicate risk") { _,_ -> journal.retryAlerts(); background { Discord.deliver(journal,Vault(this).read()); "Discord: ${journal.alertSummary()} · ${journal.meta("discordStatus")}" } }.setNegativeButton("Cancel",null).show() }
  button("Discard queued Discord messages before changing destination") { require(!SyncService.active) { "Stop workers first" }; android.app.AlertDialog.Builder(this).setTitle("Discard undelivered messages?").setMessage("Messages will not be retried. Execution journals and message evidence remain retained.").setPositiveButton("Discard") { _,_ -> journal.discardAlerts(); status.text="Queued messages discarded; destination can now be changed" }.setNegativeButton("Cancel",null).show() }
  val observation=field("Manual observation text (explicitly unverified)")
  button("Publish manual observation") { val text=observation.text.toString().trim(); require(text.isNotBlank() && text.length<=500); journal.enqueueAlert("manual:${java.util.UUID.randomUUID()}",Discord.record("manual",JSONObject().put("symbol",text).put("action","observation"))); status.text="Manual observation queued; never labelled as a broker fill" }
 }
 override fun onPause() { foreground=false; lifecycleRevision++; alertsPolling=false; guided?.stop(); guided?.let { status.text=it.evidence }; alertsTimer.removeCallbacks(alertsTick); if(::journal.isInitialized) journal.setMeta("visibility","App in background; Android may suspend or stop syncing"); super.onPause() }
 override fun onResume() { super.onResume(); foreground=true; dispatchOAuthReturn(); if(::journal.isInitialized) journal.setMeta("visibility","App foreground · explicit reconnect required after restart"); if(guided!=null) { status.text=guided!!.evidence; alertsTimer.removeCallbacks(alertsTick); alertsTimer.postDelayed(alertsTick,10000) } }
 private fun saveDiagnostics(csv:Boolean) { val records=Diagnostics.export(journal); pendingExport=if(csv) Diagnostics.csv(records) else records.toString(2); startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type=if(csv) "text/csv" else "application/json"; putExtra(Intent.EXTRA_TITLE,if(csv) "crier-diagnostics.csv" else "crier-diagnostics.json") },41) }
 override fun onActivityResult(request:Int,result:Int,data:Intent?) { super.onActivityResult(request,result,data); if(request==41 && result==RESULT_OK) { val text=pendingExport ?: return; data?.data?.let { uri -> background { contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray(Charsets.UTF_8)) } ?: error("Unable to write export"); "Diagnostics exported" } }; pendingExport=null } }
 private fun shareDiagnostics(csv:Boolean) { val records=Diagnostics.export(journal); val text=if(csv) Diagnostics.csv(records) else records.toString(2); startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { type=if(csv) "text/csv" else "application/json"; putExtra(Intent.EXTRA_SUBJECT,"Crier execution diagnostics"); putExtra(Intent.EXTRA_TEXT,text) },"Share diagnostics")) }
 override fun onDestroy() { guided?.stop(); alertsTimer.removeCallbacks(alertsTick); super.onDestroy() }
}

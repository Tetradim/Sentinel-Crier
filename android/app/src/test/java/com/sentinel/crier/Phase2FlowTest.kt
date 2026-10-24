package com.sentinel.crier
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import java.io.File

class Phase2FlowTest {
 private fun fixtures():JSONObject {
  val stream=javaClass.classLoader?.getResourceAsStream("phase2-protocol.json")
  return JSONObject(stream?.bufferedReader()?.use { it.readText() } ?: File("tests/fixtures/phase2-protocol.json").readText())
 }
 private fun base()=JSONObject(fixtures().getJSONObject("base").toString())
 @Test fun commonWireFixtures() {
  val f=fixtures(); val cases=f.getJSONArray("cases")
  for(i in 0 until cases.length()) { val c=cases.getJSONObject(i); val e=JSONObject(f.getJSONObject("base").toString()); c.getJSONObject("changes").keys().forEach { k -> e.put(k,c.getJSONObject("changes").get(k)) }; val accepted=runCatching { Journal.validate(e,"paper") }.isSuccess; assertEquals(c.getString("name"),c.getBoolean("valid"),accepted) }
 }
 @Test fun malformedAndConflictingEventsDoNotBlockFollowingRevisionOrRestart() {
  var cursor=0L; val accepted=mutableMapOf<Int,JSONObject>(); val rejected=mutableListOf<Long>()
  fun consume(rows:JSONArray) { IncomingProtocol.consume(rows,"paper",{cursor},{ e,c -> val seq=e.getInt("sequence"); require(!accepted.containsKey(seq) || IncomingProtocol.sameEvent(accepted.getValue(seq),e)); accepted[seq]=e; cursor=c },{ c,_ -> rejected.add(c); cursor=c }) }
  fun row(c:Long,e:JSONObject)=JSONObject().put("cursor",c).put("event",e)
  consume(JSONArray().put(row(1,base().put("created_at","bad"))).put(row(2,base())).put(row(3,base().put("quantity",3))).put(row(4,base().put("event_id","33333333-3333-4333-8333-333333333333").put("sequence",2))))
  assertEquals(listOf(1L,3L),rejected); assertEquals(4L,cursor); assertEquals(2,accepted.size)
  consume(JSONArray().put(row(4,base().put("sequence",9))).put(row(5,base().put("event_id","44444444-4444-4444-8444-444444444444").put("sequence",3))))
  assertEquals(5L,cursor); assertEquals(setOf(1,2,3),accepted.keys)
 }
 @Test fun eventKeyOrderIsNotAConflict() { val e=base(); val reordered=JSONObject(); e.keys().asSequence().toList().reversed().forEach { reordered.put(it,e.get(it)) }; assertTrue(IncomingProtocol.sameEvent(e,reordered)); assertFalse(IncomingProtocol.sameEvent(e,JSONObject(e.toString()).put("quantity",3))) }
 @Test fun invitationValidationAndEnvironmentSafety() {
  assertEquals("ABCDEFGHIJKLMNOP",QuickConnection.code("abcd-efgh ijkl-mnop"))
  assertEquals(QuickConnection.Invitation("https://relay.example","ABCDEFGHIJKLMNOP"),QuickConnection.invitation("https://relay.example/connect#ABCDEFGHIJKLMNOP",""))
  for(text in listOf("http://relay.example","https://user:secret@relay.example","https://relay.example/path","https://relay.example?token=x","https://relay.example#x")) assertTrue(text,runCatching { QuickConnection.origin(text) }.isFailure)
  assertTrue(runCatching { QuickConnection.invitation("https://relay.example/connect?secret=x#ABCDEFGHIJKLMNOP","") }.isFailure)
 }
 @Test fun supabaseGatewayPreservesInvitationBaseAndEndpointPath() {
  val base="https://project.supabase.co/functions/v1/crier"
  assertEquals(base,QuickConnection.origin("$base/"))
  assertEquals(QuickConnection.Invitation(base,"ABCDEFGHIJKLMNOP"),QuickConnection.invitation("$base/connect#ABCDEFGHIJKLMNOP",""))
  assertEquals("/functions/v1/crier/api/sync/events",java.net.URI("${QuickConnection.origin(base)}/api/sync/events").path)
  for(suffix in listOf("/other","?","#","/../other","//","/%63onnect")) assertTrue(suffix,runCatching { QuickConnection.origin(base+suffix) }.isFailure)
  assertTrue(runCatching { QuickConnection.invitation("$base/other/connect#ABCDEFGHIJKLMNOP","") }.isFailure)
 }
 private fun config()=JSONObject().put("account","account").put("environment","paper").put("role","host").put("url","https://relay.example").put("token","token").put("key","old-key").put("secret","old-secret")
 @Test fun settingsMigrationAndCredentialRotationKeepLegacyJournalAndIdentity() {
  val r=Settings.migrate(config()); assertEquals("intent.db",Settings.journalName(Settings.active(r)))
  val rotated=JSONObject(Settings.active(r).toString()).put("key","new-key").put("secret","new-secret")
  Settings.save(r,rotated); assertEquals("legacy",r.getString("active")); assertEquals("intent.db",Settings.journalName(Settings.active(r))); assertEquals("new-key",Settings.active(r).getString("key"))
  val reopened=Settings.migrate(JSONObject(r.toString())); assertEquals("new-secret",Settings.active(reopened).getString("secret")); assertEquals(1,reopened.getJSONArray("profiles").length())
 }
 @Test fun accountAndChannelChangesNeverReuseOwnershipJournalAndCanBeRestored() {
  val r=Settings.migrate(config()); val changed=JSONObject(config().toString()).put("account","other")
  assertTrue(runCatching { Settings.save(r,changed) }.isFailure); assertEquals("account",Settings.active(r).getString("account"))
  Settings.save(r,changed,true); assertNotEquals("intent.db",Settings.journalName(Settings.active(r))); assertEquals(2,r.getJSONArray("profiles").length())
  r.put("active","legacy"); assertEquals("account",Settings.active(r).getString("account")); assertEquals("intent.db",Settings.journalName(Settings.active(r)))
  for(key in listOf("token","url","environment","role")) assertTrue(key,runCatching { Settings.save(r,JSONObject(config().toString()).put(key,"changed")) }.isFailure)
 }
 @Test fun releaseUpgradeReopensSettingsWithoutChangingJournalOwnership() {
  val before=Settings.migrate(config()); val profile=Settings.active(before)
  val journal=Settings.journalName(profile)
  val saved=before.toString()
  val reopened=Settings.migrate(JSONObject(saved))
  assertEquals(saved,reopened.toString()); assertEquals("intent.db",journal)
  assertEquals(journal,Settings.journalName(Settings.active(reopened)))
  assertEquals("token",Settings.active(reopened).getString("token"))
 }
 @Test fun unsupportedRollbackSchemaFailsWithoutMutatingSavedSettings() {
  val newer=Settings.migrate(config()).put("schema",3)
  val saved=newer.toString()
  assertTrue(runCatching { Settings.migrate(newer) }.isFailure)
  assertEquals(saved,newer.toString())
 }
 class Alerts:AlertStore {
  val meta=mutableMapOf<String,String>(); val jobs=linkedMapOf<String,JSONObject>()
  override fun meta(key:String)=meta[key] ?: ""
  override fun setMeta(key:String,value:String) { meta[key]=value }
  override fun enqueueAlert(id:String,payload:JSONObject) { jobs.putIfAbsent(id,JSONObject().put("id",id).put("payload",payload).put("state","pending").put("attempts",0).put("next",0)) }
  override fun claimAlert(now:Long,id:String?):JSONObject? { val j=jobs.values.firstOrNull { (id==null || it.getString("id")==id) && it.getString("state")=="pending" && it.getLong("next")<=now } ?: return null; j.put("state","uncertain").put("attempts",j.getInt("attempts")+1); return j }
  override fun alertResult(id:String,state:String,delay:Long,detail:String) { val j=jobs.getValue(id); j.put("state",state).put("next",System.currentTimeMillis()+delay).put("detail",detail) }
 }
 private fun destination()=JSONObject().put("discordWebhook","https://discord.com/api/webhooks/123/secret").put("discordStyle","plain")
 @Test fun discordProvenanceAlwaysVisibleAndMentionsSuppressed() {
  for(source in listOf("intent","manual","broker_fill","test")) {
   val c=destination().put("discordTemplate","{symbol} @everyone").put("discordFields","quantity,price")
   val p=Discord.payload(Discord.record(source,base()),c); assertTrue(p.getString("content").startsWith(Discord.label(source))); assertEquals(0,p.getJSONObject("allowed_mentions").getJSONArray("parse").length()); assertFalse(p.getString("content").contains("trade_id:"))
   c.put("discordStyle","card"); assertEquals(Discord.label(source),Discord.payload(Discord.record(source,base()),c).getJSONArray("embeds").getJSONObject(0).getString("title"))
  }
  assertTrue(runCatching { Discord.payload(Discord.sample(),destination().put("discordTemplate","{secret}")) }.isFailure)
 }
 @Test fun deliveredMessageHasReceiptAndNeverResends() {
  val s=Alerts(); Discord.test(s); var sends=0
  fun deliver()=Discord.deliver(s,destination()) { url,body -> assertTrue(url.endsWith("?wait=true")); assertTrue(body.getString("content").startsWith("TEST MESSAGE")); sends++; JSONObject().put("id","12345") }
  deliver(); deliver(); assertEquals(1,sends); assertEquals("delivered",s.jobs.values.single().getString("state"))
 }
 @Test fun testMessageNeverDispatchesAnOlderRealAlert() {
  val s=Alerts(); s.enqueueAlert("real",Discord.record("intent",base())); val test=Discord.test(s)
  Discord.deliver(s,destination(),jobId=test) { _,payload -> assertTrue(payload.getString("content").startsWith("TEST MESSAGE")); JSONObject().put("id","12345") }
  assertEquals("pending",s.jobs.getValue("real").getString("state")); assertEquals("delivered",s.jobs.getValue(test).getString("state"))
 }
 @Test fun brokerFillNeverInventsAnExecutionPriceFromIntentLimit() {
  val order=JSONObject().put("filled_qty","1").put("status","partially_filled")
  assertEquals("Unavailable",Discord.brokerFill(base(),order,"buy").getString("price"))
  order.put("filled_avg_price","0.23"); val record=Discord.brokerFill(base(),order,"buy")
  assertEquals("0.23",record.getString("price")); assertEquals("1",record.getString("quantity")); assertTrue(record.getString("status").contains("cumulative"))
  assertTrue(runCatching { Discord.brokerFill(base(),order.put("filled_qty","0"),"buy") }.isFailure)
 }
 @Test fun missingReceiptAndCrashReservationNeverBlindlyRetry() {
  for(crash in listOf(false,true)) { val s=Alerts(); Discord.test(s); var sends=0
   if(crash) s.claimAlert(System.currentTimeMillis()) else Discord.deliver(s,destination()) { _,_ -> sends++; JSONObject() }
   Discord.deliver(s,destination()) { _,_ -> sends++; JSONObject().put("id","123") }
   assertEquals(if(crash) 0 else 1,sends); assertEquals("uncertain",s.jobs.values.single().getString("state"))
  }
 }
 @Test fun definitiveDiscordRejectionsBlockAndRateLimitDefersChannel() {
  for(code in listOf(400,401,403,404,429,500)) { val s=Alerts(); Discord.test(s); Discord.deliver(s,destination()) { _,_ -> throw HttpError(code,60) }; assertEquals("HTTP $code",when(code) { 429->"pending"; 500->"uncertain"; else->"blocked" },s.jobs.values.single().getString("state")); if(code==429) assertTrue(s.meta("discordRetryAt").toLong()>System.currentTimeMillis()+59000) }
 }
}

package com.sentinel.crier
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.util.UUID
import java.time.Instant

/** Device SQLite/vault coverage; no transport or service is started. */
@RunWith(AndroidJUnit4::class)
class LivePolicyPersistenceTest {
 private val context:Context get()=ApplicationProvider.getApplicationContext()
 private fun event()=JSONObject().put("version",1).put("event_id",UUID.randomUUID().toString()).put("trade_id",UUID.randomUUID().toString()).put("sequence",1).put("action","enter").put("environment","paper").put("symbol","SPY").put("asset","stock").put("quantity",10).put("limit_price","1.00").put("created_at",Instant.now().toString()).put("expires_at",Instant.now().plusSeconds(20).toString())
 private fun oldDatabase(name:String,advanced:Boolean=false) {
  context.openOrCreateDatabase(name,Context.MODE_PRIVATE,null).use { db ->
   db.execSQL("CREATE TABLE events(id TEXT PRIMARY KEY, trade TEXT, seq INTEGER, payload TEXT, outgoing INTEGER, sent INTEGER DEFAULT 0, done INTEGER DEFAULT 0, UNIQUE(trade,seq))")
   db.execSQL("CREATE TABLE trades(id TEXT PRIMARY KEY, seq INTEGER, invalid INTEGER DEFAULT 0)")
   db.execSQL("CREATE TABLE orders(client TEXT PRIMARY KEY, trade TEXT, seq INTEGER, side TEXT, state TEXT, broker TEXT DEFAULT '', filled INTEGER DEFAULT 0)")
   db.execSQL("CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT)")
   db.execSQL("INSERT INTO trades VALUES('old-trade',1,0)")
   if(advanced) db.execSQL("INSERT INTO meta VALUES('plan:old-trade:1','{}')")
   db.version=3
  }
 }
 @Test fun migrationExplicitlyPinsLegacyAndCurrentMissingMarkerFailsClosed() {
  val name="policy-test-${UUID.randomUUID()}.db"
  try {
   oldDatabase(name)
   Journal(context,name).use { j -> assertTrue(j.policy("old-trade").getBoolean("legacy")); assertEquals("1",j.meta("policy_schema")); j.writableDatabase.execSQL("DELETE FROM meta WHERE k='policy_schema'"); assertThrows(IllegalArgumentException::class.java) { j.policy("old-trade") } }
   Journal(context,name).use { j -> assertThrows(IllegalArgumentException::class.java) { j.policy("old-trade") } }
  } finally { context.deleteDatabase(name) }
 }
 @Test fun downgradeEvidenceIsRetainedAndDoesNotMigrateAsLegacy() {
  val name="policy-test-${UUID.randomUUID()}.db"
  try { oldDatabase(name,true); Journal(context,name).use { j -> assertThrows(IllegalArgumentException::class.java) { j.writableDatabase } } }
  finally { context.deleteDatabase(name) }
 }
 @Test fun receiptSnapshotAndAtomicReconciliationEvidenceSurviveReopen() {
  val name="policy-test-${UUID.randomUUID()}.db"; val vault=Vault(context); val original=vault.readDocument(); val e=event(); val trade=e.getString("trade_id")
  val c=JSONObject().put("role","follower").put("environment","paper").put("account","test-account").put("url","https://relay.example").put("token","fake-pairing").put("execution_policy",JSONObject().put("mode","fixed").put("fixed_quantity",3))
  try {
   vault.writeDocument(Settings.migrate(c))
   Journal(context,name).use { j ->
    j.accept(e); c.getJSONObject("execution_policy").put("fixed_quantity",9); vault.writeDocument(Settings.migrate(c)); j.accept(e)
    assertEquals(3,j.policy(trade).getJSONObject("policy").getInt("fixed_quantity"))
    j.unknown("test-client",trade,1,"buy")
    val response=JSONObject().put("id","broker").put("client_order_id","test-client").put("symbol","SPY").put("side","buy").put("qty","3").put("status","partially_filled").put("filled_qty","1").put("filled_avg_price","1.25")
    j.updateObserved("test-client",response,"acknowledged")
    assertEquals("1.25",JSONObject(j.meta("fill:test-client")).getString("average"))
    response.put("filled_qty","2").remove("filled_avg_price"); j.updateObserved("test-client",response,"acknowledged")
    assertEquals("",j.meta("fill:test-client"))
   }
   Journal(context,name).use { j -> assertEquals(3,j.policy(trade).getJSONObject("policy").getInt("fixed_quantity")); assertEquals(2,j.orders(trade).single().filled); assertEquals("acknowledged",j.meta("timer:test-client")); assertEquals("",j.meta("fill:test-client")); j.writableDatabase.execSQL("DELETE FROM meta WHERE k=?",arrayOf("policy:$trade")); assertThrows(IllegalArgumentException::class.java) { j.policy(trade) } }
  } finally { vault.writeDocument(original); context.deleteDatabase(name) }
 }
}

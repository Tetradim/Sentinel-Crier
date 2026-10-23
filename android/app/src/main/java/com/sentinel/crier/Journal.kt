package com.sentinel.crier
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.time.Instant
import java.util.UUID
class Journal(context: Context,name:String=Settings.journalName(Vault(context).read())): SQLiteOpenHelper(context,name,null,3), IntentStore, AlertStore {
 override fun onCreate(db: SQLiteDatabase) {
  db.execSQL("CREATE TABLE events(id TEXT PRIMARY KEY, trade TEXT, seq INTEGER, payload TEXT, outgoing INTEGER, sent INTEGER DEFAULT 0, done INTEGER DEFAULT 0, UNIQUE(trade,seq))")
  db.execSQL("CREATE TABLE trades(id TEXT PRIMARY KEY, seq INTEGER, invalid INTEGER DEFAULT 0)")
  db.execSQL("CREATE TABLE orders(client TEXT PRIMARY KEY, trade TEXT, seq INTEGER, side TEXT, state TEXT, broker TEXT DEFAULT '', filled INTEGER DEFAULT 0)")
  db.execSQL("CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT)")
  diagnosticsSchema(db)
  recoverySchema(db)
 }
 private fun diagnosticsSchema(db:SQLiteDatabase) { runCatching { db.execSQL("CREATE TABLE IF NOT EXISTS diagnostics(event TEXT, at TEXT, stage TEXT, detail TEXT)") } }
 private fun recoverySchema(db:SQLiteDatabase) {
  db.execSQL("CREATE TABLE IF NOT EXISTS rejected(cursor INTEGER PRIMARY KEY,reason TEXT)")
  db.execSQL("CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY,payload TEXT,state TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next INTEGER DEFAULT 0,detail TEXT DEFAULT '')")
 }
 override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) { if(old<2) diagnosticsSchema(db); if(old<3) recoverySchema(db) }
 @Synchronized fun reject(cursor:Long,reason:String) { val db=writableDatabase; db.beginTransaction(); try { db.execSQL("INSERT OR REPLACE INTO rejected VALUES(?,?)",arrayOf(cursor,reason.take(300))); setMeta("cursor",cursor.toString()); setMeta("protocolStatus","Rejected event at cursor $cursor: ${reason.take(200)}"); db.setTransactionSuccessful() } finally { db.endTransaction() } }
 @Synchronized override fun enqueueAlert(id:String,payload:JSONObject) { writableDatabase.execSQL("INSERT OR IGNORE INTO alerts(id,payload) VALUES(?,?)",arrayOf(id,payload.toString())) }
 @Synchronized fun alert(now:Long,id:String?=null):JSONObject? = readableDatabase.rawQuery("SELECT id,payload,attempts FROM alerts WHERE state='pending' AND next<=?"+(if(id!=null) " AND id=?" else "")+" ORDER BY rowid LIMIT 1",if(id!=null) arrayOf(now.toString(),id) else arrayOf(now.toString())).use { if(it.moveToFirst()) JSONObject().put("id",it.getString(0)).put("payload",JSONObject(it.getString(1))).put("attempts",it.getInt(2)) else null }
 @Synchronized override fun claimAlert(now:Long,id:String?):JSONObject? {
  val db=writableDatabase; db.beginTransaction()
  try { val next=alert(now,id); if(next!=null) { db.execSQL("UPDATE alerts SET state='uncertain',attempts=attempts+1,detail='Dispatch reserved; acknowledgement pending' WHERE id=?",arrayOf(next.getString("id"))); setMeta("discordStatus","Dispatch reserved; acknowledgement pending. Inspect Discord before retrying.") }; db.setTransactionSuccessful(); return next }
  finally { db.endTransaction() }
 }
 @Synchronized override fun alertResult(id:String,state:String,delay:Long,detail:String) { writableDatabase.execSQL("UPDATE alerts SET state=?,next=?,detail=? WHERE id=?",arrayOf(state,System.currentTimeMillis()+delay,detail,id)); setMeta("discordStatus","$state: $detail") }
 @Synchronized fun hasUndeliveredAlerts():Boolean = readableDatabase.rawQuery("SELECT COUNT(*) FROM alerts WHERE state IN ('pending','blocked','uncertain')",null).use { it.moveToFirst(); it.getInt(0)>0 }
 @Synchronized fun discardAlerts() { writableDatabase.execSQL("UPDATE alerts SET state='discarded',detail='Explicitly discarded by user before destination change' WHERE state IN ('pending','blocked','uncertain')") }
 @Synchronized fun retryAlerts() { writableDatabase.execSQL("UPDATE alerts SET state='pending',next=0 WHERE state IN ('pending','blocked','uncertain')") }
 @Synchronized fun alertSummary():String = readableDatabase.rawQuery("SELECT state,COUNT(*) FROM alerts GROUP BY state",null).use { c -> buildList { while(c.moveToNext()) add("${c.getString(0)}: ${c.getInt(1)}") }.joinToString(", ").ifBlank { "No queued messages" } }
 @Synchronized fun unresolved():String = readableDatabase.rawQuery("SELECT client,state,filled FROM orders WHERE state NOT IN ('filled','canceled','expired','rejected','replaced','superseded')",null).use { c -> buildList { while(c.moveToNext()) add("${c.getString(0)} Â· ${c.getString(1)} Â· filled ${c.getInt(2)}") }.joinToString("\n").ifBlank { "No unresolved broker orders" } }
 @Synchronized fun evidence(id:String,stage:String,detail:String="",at:String=Instant.now().toString()) { runCatching { writableDatabase.execSQL("INSERT INTO diagnostics VALUES(?,?,?,?)",arrayOf(id,at,stage,detail)) } }
 @Synchronized override fun diagnostic(id:String,stage:String,detail:String) { runCatching { val key="timeline:$id:$stage"; if(meta(key)!=detail) { evidence(id,stage,detail); setMeta(key,detail) } } }
 @Synchronized fun diagnosticEvents():List<JSONObject> = readableDatabase.rawQuery("SELECT payload FROM events ORDER BY rowid DESC LIMIT 200",null).use { c -> buildList { while(c.moveToNext()) add(JSONObject(c.getString(0))) } }
 @Synchronized fun timeline(id:String):org.json.JSONArray = readableDatabase.rawQuery("SELECT at,stage,detail FROM diagnostics WHERE event=? ORDER BY rowid",arrayOf(id)).use { c -> org.json.JSONArray().also { a -> while(c.moveToNext()) a.put(JSONObject().put("at",c.getString(0)).put("stage",c.getString(1)).put("detail",c.getString(2))) } }
 private fun orderEvidence(client:String,stage:String,detail:String) { runCatching { readableDatabase.rawQuery("SELECT e.id FROM events e JOIN orders o ON e.trade=o.trade AND e.seq=o.seq WHERE o.client=?",arrayOf(client)).use { if(it.moveToFirst()) evidence(it.getString(0),stage,detail) } } }
 @Synchronized override fun meta(key: String): String = readableDatabase.rawQuery("SELECT v FROM meta WHERE k=?",arrayOf(key)).use { if(it.moveToFirst()) it.getString(0) else "" }
 @Synchronized override fun setMeta(key: String,value: String) { writableDatabase.execSQL("INSERT OR REPLACE INTO meta VALUES(?,?)",arrayOf(key,value)) }
 @Synchronized fun accept(e: JSONObject, outgoing: Boolean = false, cursor: Long? = null, skipEntry: Boolean = false) {
  val db = writableDatabase; db.beginTransaction()
  try {
   val id=e.getString("event_id"); val trade=e.getString("trade_id"); val seq=e.getInt("sequence")
   db.rawQuery("SELECT payload FROM events WHERE id=? OR (trade=? AND seq=?)",arrayOf(id,trade,seq.toString())).use { if(it.moveToFirst()) { require(IncomingProtocol.sameEvent(JSONObject(it.getString(0)),e)) { "Event conflict" }; if(cursor!=null) setMeta("cursor",cursor.toString()); db.setTransactionSuccessful(); return } }
   db.rawQuery("SELECT payload FROM events WHERE trade=? LIMIT 1",arrayOf(trade)).use { if(it.moveToFirst()) { val original=JSONObject(it.getString(0)); for(k in listOf("symbol","asset","environment")) require(original.getString(k)==e.getString(k)) { "Trade identity changed" } } }
   db.execSQL("INSERT INTO events(id,trade,seq,payload,outgoing) VALUES(?,?,?,?,?)",arrayOf(id,trade,seq,e.toString(),if(outgoing) 1 else 0))
   evidence(id,if(outgoing) "sender" else "receiver",at=Instant.now().toString())
   if(outgoing) enqueueAlert("intent:$id",Discord.record("intent",e))
   db.execSQL("INSERT OR IGNORE INTO trades(id,seq) VALUES(?,0)",arrayOf(trade))
   db.execSQL("UPDATE trades SET seq=MAX(seq,?),invalid=MAX(invalid,?) WHERE id=?",arrayOf(seq,if(e.getString("action") in setOf("cancel","exit")) 1 else 0,trade))
   if(skipEntry && e.getString("action") in setOf("enter","replace")) db.execSQL("UPDATE events SET done=1 WHERE id=?",arrayOf(id))
   if(cursor!=null) setMeta("cursor",cursor.toString())
   db.setTransactionSuccessful()
  } finally { db.endTransaction() }
 }
 @Synchronized override fun create(action: String,symbol: String,asset: String,quantity: Int,price: String,environment: String,tradeId: String): JSONObject {
  val seq = revision(tradeId).first + 1
  val now=Instant.now()
  val e=JSONObject().put("version",1).put("event_id",UUID.randomUUID().toString()).put("trade_id",tradeId).put("sequence",seq).put("action",action).put("environment",environment).put("symbol",symbol).put("asset",asset).put("quantity",quantity).put("limit_price",price).put("created_at",now.toString()).put("expires_at",now.plusSeconds(30).toString())
  validate(e,environment); accept(e,true); return e
 }
 @Synchronized override fun revision(trade: String): Pair<Int,Boolean> = readableDatabase.rawQuery("SELECT seq,invalid FROM trades WHERE id=?",arrayOf(trade)).use { if(it.moveToFirst()) Pair(it.getInt(0),it.getInt(1)==1) else Pair(0,false) }
 @Synchronized fun events(outbox: Boolean): List<JSONObject> = readableDatabase.rawQuery(if(outbox) "SELECT payload FROM events WHERE outgoing=1 AND sent=0 ORDER BY rowid" else "SELECT payload FROM events WHERE done=0 ORDER BY rowid",null).use { c -> buildList { while(c.moveToNext()) add(JSONObject(c.getString(0))) } }
 @Synchronized override fun mark(id: String, outbox: Boolean) { writableDatabase.execSQL("UPDATE events SET ${if(outbox) "sent" else "done"}=1 WHERE id=?",arrayOf(id)); evidence(id,if(outbox) "outbox_complete" else "execution_complete") }
 data class Order(val client:String,val sequence:Int,val side:String,val state:String,val broker:String,val filled:Int)
 @Synchronized override fun orders(trade: String): List<Order> = readableDatabase.rawQuery("SELECT client,seq,side,state,broker,filled FROM orders WHERE trade=?",arrayOf(trade)).use { c -> buildList { while(c.moveToNext()) add(Order(c.getString(0),c.getInt(1),c.getString(2),c.getString(3),c.getString(4),c.getInt(5))) } }
 @Synchronized override fun unknown(client:String,trade:String,seq:Int,side:String) { writableDatabase.execSQL("INSERT INTO orders(client,trade,seq,side,state) VALUES(?,?,?,?,'unknown')",arrayOf<Any>(client,trade,seq,side)); orderEvidence(client,"submit_attempt",side) }
 @Synchronized override fun state(client:String,state:String) { writableDatabase.execSQL("UPDATE orders SET state=? WHERE client=?",arrayOf(state,client)); orderEvidence(client,"order_state",state) }
 @Synchronized override fun update(client:String,o:JSONObject) {
  val db=writableDatabase; db.beginTransaction()
  try {
   db.execSQL("UPDATE orders SET state=?,broker=?,filled=? WHERE client=?",arrayOf(o.getString("status"),o.getString("id"),o.optString("filled_qty","0").toBigDecimal().toInt(),client))
   val detail=JSONObject().put("client_order_id",client).put("id",o.getString("id")).put("status",o.getString("status")).put("filled_qty",o.optString("filled_qty","0")).put("filled_avg_price",o.opt("filled_avg_price") ?: JSONObject.NULL).put("created_at",o.opt("created_at") ?: JSONObject.NULL).put("filled_at",o.opt("filled_at") ?: JSONObject.NULL).toString()
   if(meta("lastEvidence:$client")!=detail) { orderEvidence(client,"broker_reconciled",detail); setMeta("lastEvidence:$client",detail) }
   val filled=o.optString("filled_qty","0").toBigDecimal()
   if(filled.signum()>0) db.rawQuery("SELECT e.payload,o.side FROM events e JOIN orders o ON e.trade=o.trade AND e.seq=o.seq WHERE o.client=?",arrayOf(client)).use { c -> if(c.moveToFirst()) {
    val e=JSONObject(c.getString(0)); val record=Discord.brokerFill(e,o,c.getString(1))
    enqueueAlert("fill:$client:${filled.stripTrailingZeros().toPlainString()}",record)
   } }
   db.setTransactionSuccessful()
  } finally { db.endTransaction() }
 }
 @Synchronized fun history():List<JSONObject> = readableDatabase.rawQuery("SELECT payload FROM events e WHERE seq=(SELECT MAX(seq) FROM events latest WHERE latest.trade=e.trade) ORDER BY rowid DESC LIMIT 100",null).use { c -> buildList { while(c.moveToNext()) add(JSONObject(c.getString(0))) } }
 fun summary(): String = events(false).joinToString("\n") { "${it.getString("action")} ${it.getString("symbol")} â€¢ ${it.getString("trade_id")}" }.ifBlank { "No pending intents" }
 companion object {
  fun validate(e:JSONObject,environment:String) {
   require(e.keys().asSequence().toSet()==setOf("version","event_id","trade_id","sequence","action","environment","symbol","asset","quantity","limit_price","created_at","expires_at"))
   require(e.getInt("version")==1 && e.get("version").toString()=="1" && e.getString("environment")==environment)
   for(k in listOf("event_id","trade_id")) require(UUID.fromString(e.getString(k)).toString()==e.getString(k))
   require(e.get("sequence").toString()==e.getInt("sequence").toString() && e.getInt("sequence")>0 && e.getString("action") in setOf("enter","replace","cancel","exit"))
   require(e.getString("asset") in setOf("stock","option") && e.getString("symbol").matches(if(e.getString("asset")=="option") Regex("[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}") else Regex("[A-Z][A-Z0-9.]{0,14}")))
   if(e.getString("asset")=="option") { val symbol=e.getString("symbol"); val date=symbol.takeLast(15).take(6); java.time.LocalDate.of(2000+date.take(2).toInt(),date.substring(2,4).toInt(),date.takeLast(2).toInt()); require(symbol.takeLast(8).toLong()>0) }
   require(e.get("quantity").toString()==e.getInt("quantity").toString() && e.getInt("quantity") in 1..1000 && e.get("limit_price") is String && e.getString("limit_price").toBigDecimal().signum()>0)
   val created=Instant.parse(e.getString("created_at")); val expires=Instant.parse(e.getString("expires_at"))
   require(expires>=created && (e.getString("action") !in setOf("enter","replace") || expires<=created.plusSeconds(30)))
  }
 }
}

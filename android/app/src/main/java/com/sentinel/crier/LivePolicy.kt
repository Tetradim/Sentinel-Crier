package com.sentinel.crier
import org.json.JSONObject
import java.math.BigDecimal
import java.math.RoundingMode

/** Pure arithmetic and durable, credential-free follower policy records. */
object LivePolicy {
 private val fields=setOf("version","mode","fixed_quantity","ratio_bps","budget","max_source_quantity","max_local_quantity","max_entry_notional","exit_mode","entry_timeout_seconds")
 fun validate(p:JSONObject):JSONObject {
  require(p.keys().asSequence().all { it in fields }) { "Unknown execution policy field" }
  fun integer(k:String,default:Int?,range:IntRange):Int? {
   if(!p.has(k)) return default
   if(p.isNull(k)) { require(default==null) { "$k cannot be null" }; return null }
   val v=p.get(k); require(v is Int || v is Long) { "$k must be an integer" }; val n=(v as Number).toLong(); require(n in range.first.toLong()..range.last.toLong()); return n.toInt()
  }
  fun decimal(k:String):String? {
   if(!p.has(k) || p.isNull(k)) return null
   val v=p.get(k); require(v is String && v.matches(Regex("(?:0|[1-9][0-9]*)(\\.[0-9]{1,8})?")) && v.replace(".","").length<=20 && BigDecimal(v).signum()>0) { "$k must be a positive decimal string" }; return v
  }
  for(k in listOf("mode","exit_mode")) require(!p.has(k) || p.get(k) is String)
  val mode=p.optString("mode","source"); val exit=p.optString("exit_mode","requested")
  require(mode in setOf("source","fixed","ratio","budget") && exit in setOf("requested","proportional","close_tracked"))
  require(integer("version",1,1..1)==1)
  val fixed=integer("fixed_quantity",null,1..1000); val ratio=integer("ratio_bps",null,1..10000); val budget=decimal("budget")
  require((mode=="fixed")== (fixed!=null) && (mode=="ratio")== (ratio!=null) && (mode=="budget")== (budget!=null)) { "Missing or unused sizing field" }
  return JSONObject().put("version",1).put("mode",mode).put("fixed_quantity",fixed ?: JSONObject.NULL).put("ratio_bps",ratio ?: JSONObject.NULL).put("budget",budget ?: JSONObject.NULL).put("max_source_quantity",integer("max_source_quantity",1000,1..1000)).put("max_local_quantity",integer("max_local_quantity",1000,1..1000)).put("max_entry_notional",decimal("max_entry_notional") ?: JSONObject.NULL).put("exit_mode",exit).put("entry_timeout_seconds",integer("entry_timeout_seconds",null,1..86400) ?: JSONObject.NULL)
 }
 fun selected(c:JSONObject):JSONObject? {
  if(c.optString("role")!="follower" || !c.has("execution_policy") || c.isNull("execution_policy")) return null
  return validate(c.getJSONObject("execution_policy")).also { require(c.optString("mode","exact_limit")!="market" || (it.getString("mode")!="budget" && it.isNull("max_entry_notional"))) { "Market pricing cannot guarantee budget or notional caps" } }
 }
 fun equivalent(a:JSONObject,b:JSONObject):Boolean = a.keys().asSequence().toSet()==b.keys().asSequence().toSet() && a.keys().asSequence().all { k -> val x=a.get(k); val y=b.get(k); if(x is JSONObject && y is JSONObject) equivalent(x,y) else x.toString()==y.toString() }
 fun selection(c:JSONObject):String = selected(c)?.let { p -> p.keys().asSequence().sorted().joinToString("|") { "$it=${p.get(it)}" } } ?: "legacy"
 fun scope(c:JSONObject):String {
  if(c.optString("url").isBlank() || c.optString("token").isBlank()) return ""
  return java.security.MessageDigest.getInstance("SHA-256").digest((c.getString("url").trimEnd('/')+"\n"+c.getString("token")).toByteArray()).joinToString("") { "%02x".format(it) }
 }
 fun snapshot(c:JSONObject,e:JSONObject):JSONObject {
  val policy=selected(c) ?: return JSONObject().put("legacy",true)
  policy.put("max_source_quantity",minOf(policy.getInt("max_source_quantity"),c.optInt("maxQuantity",1000)))
  return JSONObject().put("legacy",false).put("policy",policy).put("scope",scope(c)).put("role",c.optString("role")).put("account",c.optString("account")).put("environment",c.optString("environment")).put("symbol",e.getString("symbol")).put("asset",e.getString("asset"))
 }
 fun requireBinding(s:JSONObject,c:JSONObject,e:JSONObject) {
  require(s.getString("scope").isNotBlank() && s.getString("scope")==scope(c)) { "Policy pairing scope missing or changed" }
  for(k in listOf("role","account","environment")) require(s.getString(k).isNotBlank() && s.getString(k)==c.optString(k)) { "Policy $k changed" }
  for(k in listOf("symbol","asset","environment")) require(s.getString(k)==e.getString(k)) { "Policy instrument changed" }
  require(s.getString("role")=="follower")
 }
 fun multiplier(asset:String,size:Int?):Int {
  require(asset in setOf("stock","option"))
  val expected=if(asset=="option") 100 else 1
  require((size ?: if(asset=="stock") 1 else 0)==expected) { "Verified standard instrument multiplier required" }
  return expected
 }
 fun target(raw:JSONObject,source:Int,price:String?,multiplier:Int,bought:Int,spent:BigDecimal):Int {
  val p=validate(raw); require(source in 1..p.getInt("max_source_quantity")) { "Source quantity cap" }
  val unit=price?.toBigDecimal()?.multiply(multiplier.toBigDecimal())
  require((p.getString("mode")!="budget" && p.isNull("max_entry_notional")) || unit!=null) { "Valuation unavailable" }
  val n=when(p.getString("mode")) {
   "fixed"->p.getInt("fixed_quantity")
   "ratio"->source*p.getInt("ratio_bps")/10000
   "budget"->bought+p.getString("budget").toBigDecimal().subtract(spent).max(BigDecimal.ZERO).divide(unit!!,0,RoundingMode.FLOOR).min(BigDecimal(1001)).toInt()
   else->source
  }
  require(n<=p.getInt("max_local_quantity")) { "Local quantity cap" }
  if(!p.isNull("max_entry_notional")) require(spent.add(unit!!.multiply((n-bought).coerceAtLeast(0).toBigDecimal()))<=p.getString("max_entry_notional").toBigDecimal()) { "Entry notional cap" }
  return n
 }
 fun validateSnapshot(s:JSONObject):JSONObject {
  require(s.get("legacy") is Boolean) { "Invalid policy marker" }
  if(s.getBoolean("legacy")) require(s.keys().asSequence().toSet()==setOf("legacy")) { "Contradictory legacy snapshot" }
  else {
   require(s.keys().asSequence().toSet()==setOf("legacy","policy","scope","role","account","environment","symbol","asset")) { "Invalid policy snapshot schema" }
   require(equivalent(validate(s.getJSONObject("policy")),s.getJSONObject("policy"))) { "Noncanonical policy snapshot" }
   for(k in listOf("scope","role","account","environment","symbol","asset")) require(s.get(k) is String)
   require(s.getString("role")=="follower" && s.getString("environment") in setOf("paper","live") && s.getString("asset") in setOf("stock","option"))
  }
  return s
 }
 fun validatePlan(plan:JSONObject,snapshot:JSONObject,event:JSONObject,bought:Int) {
  require(plan.keys().asSequence().toSet()==setOf("event","snapshot","binding","price","target","baseline_bought","baseline_spent","pricing")) { "Frozen plan schema invalid" }
  require(IncomingProtocol.sameEvent(plan.getJSONObject("event"),event) && equivalent(plan.getJSONObject("snapshot"),snapshot)) { "Frozen plan identity changed" }
  val binding=plan.getJSONObject("binding")
  require(binding.keys().asSequence().toSet()==setOf("account","environment","symbol","asset","currency","multiplier"))
  for(k in listOf("account","environment","symbol","asset")) require(binding.getString(k)==snapshot.getString(k))
  require(binding.getString("currency")=="USD" && binding.get("multiplier") is Int && binding.getInt("multiplier")==if(snapshot.getString("asset")=="option") 100 else 1)
  require(plan.get("target") is Int && plan.get("baseline_bought") is Int)
  val baseline=plan.getInt("baseline_bought"); require(baseline in 0..bought)
  require(plan.get("baseline_spent") is String && plan.getString("baseline_spent").matches(Regex("[0-9]+(\\.[0-9]+)?")))
  val spent=plan.getString("baseline_spent").toBigDecimal()
  val price=if(plan.isNull("price")) null else plan.getString("price").also { require(plan.get("price") is String && it.toBigDecimal().signum()>0) }
  val basis=plan.getJSONObject("pricing")
  require(basis.keys().asSequence().toSet()==setOf("mode","bps","amount") && basis.get("mode") is String && basis.get("bps") is Int && basis.get("amount") is String)
  val recomputedPrice=Policy.price(event.getString("limit_price"),basis.getString("mode"),false,basis.getInt("bps"),basis.getString("amount"))
  require((price==null && recomputedPrice==null) || (price!=null && recomputedPrice!=null && price.toBigDecimal().compareTo(recomputedPrice.toBigDecimal())==0)) { "Frozen price contradicts source and pricing basis" }
  val expected=target(snapshot.getJSONObject("policy"),event.getInt("quantity"),price,binding.getInt("multiplier"),baseline,spent)
  require(plan.getInt("target")==expected) { "Frozen target contradicts policy and basis" }
 }
 fun sourceIntent(events:List<JSONObject>):Pair<Int,Int> {
  require(events.isNotEmpty()); val sorted=events.sortedBy { it.getInt("sequence") }; var denominator=0; var exits=0L; var closed=false
  sorted.forEachIndexed { i,e ->
   require(e.getInt("sequence")==i+1 && (i!=0 || e.getString("action")=="enter")) { "Incomplete source history" }
   for(k in listOf("trade_id","symbol","asset","environment")) require(e.getString(k)==sorted[0].getString(k))
   when(e.getString("action")) {
    "enter","replace"->{ require(!closed && (i==0 || e.getString("action")=="replace")); denominator=e.getInt("quantity") }
    "exit"->{ closed=true; exits+=e.getInt("quantity") }
    "cancel"->closed=true
    else->throw IllegalArgumentException("Invalid source action")
   }
  }
  require(denominator>0); return Pair(denominator,minOf(exits,denominator.toLong()).toInt())
 }
 fun spent(store:IntentStore,orders:List<Journal.Order>,multiplier:Int):BigDecimal {
  var total=BigDecimal.ZERO
  for(o in orders.filter { it.side=="buy" && it.filled>0 }) {
   val evidence=JSONObject(store.meta("fill:${o.client}").ifBlank { throw IllegalArgumentException("Fill cost unavailable") })
   require(evidence.keys().asSequence().toSet()==setOf("filled","average") && evidence.get("filled") is Int && evidence.getInt("filled")==o.filled) { "Fill cost is stale or corrupt" }
   require(evidence.get("average") is String)
   val average=evidence.getString("average").toBigDecimal(); require(average.signum()>0) { "Fill average must be positive" }
   total=total.add(average.multiply(o.filled.toBigDecimal()).multiply(multiplier.toBigDecimal()))
  }
  return total
 }
}

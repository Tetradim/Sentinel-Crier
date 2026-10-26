package com.sentinel.crier
import org.json.JSONObject
interface AlertStore {
 fun meta(key:String):String
 fun setMeta(key:String,value:String)
 fun enqueueAlert(id:String,payload:JSONObject)
 fun claimAlert(now:Long,id:String?=null):JSONObject?
 fun alertResult(id:String,state:String,delay:Long,detail:String)
 fun healthStates():Set<String>?=null
}
interface IntentStore {
 fun bindPolicyAccount(trade:String,account:String):JSONObject = policy(trade)
 fun policy(trade:String):JSONObject = JSONObject().put("legacy",true)
 fun sourceEvents(trade:String):List<JSONObject> = emptyList()
 fun diagnostic(id:String,stage:String,detail:String) {}
 fun meta(key:String):String
 fun setMeta(key:String,value:String)
 fun revision(trade:String):Pair<Int,Boolean>
 fun orders(trade:String):List<Journal.Order>
 fun mark(id:String,outbox:Boolean)
 fun state(client:String,state:String)
 fun updateObserved(client:String,o:JSONObject,timer:String?) { synchronized(this) { update(client,o); if(timer!=null) setMeta("timer:$client",timer) } }
 fun update(client:String,o:JSONObject)
 fun unknown(client:String,trade:String,seq:Int,side:String)
 fun create(action:String,symbol:String,asset:String,quantity:Int,price:String,environment:String,tradeId:String = java.util.UUID.randomUUID().toString()):JSONObject
}
interface BrokerPort {
 fun binding(event:JSONObject):JSONObject = throw IllegalArgumentException("Checked broker metadata unsupported")
 fun submitPlanned(event:JSONObject,client:String,quantity:Int,sell:Boolean,plan:JSONObject,canSubmit:()->Boolean):JSONObject = throw Superseded()
 fun account():String
 fun order(client:String):JSONObject?
 fun cancel(id:String)
 fun holdings(symbol:String):Int
 fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean):JSONObject
}

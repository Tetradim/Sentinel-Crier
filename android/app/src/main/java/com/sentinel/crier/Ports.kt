package com.sentinel.crier
import org.json.JSONObject
interface IntentStore {
 fun meta(key:String):String
 fun setMeta(key:String,value:String)
 fun revision(trade:String):Pair<Int,Boolean>
 fun orders(trade:String):List<Journal.Order>
 fun mark(id:String,outbox:Boolean)
 fun state(client:String,state:String)
 fun update(client:String,o:JSONObject)
 fun unknown(client:String,trade:String,seq:Int,side:String)
 fun create(action:String,symbol:String,asset:String,quantity:Int,price:String,environment:String,tradeId:String = java.util.UUID.randomUUID().toString()):JSONObject
}
interface BrokerPort {
 fun account():String
 fun order(client:String):JSONObject?
 fun cancel(id:String)
 fun holdings(symbol:String):Int
 fun submit(event:JSONObject,client:String,quantity:Int,sell:Boolean,canSubmit:()->Boolean):JSONObject
}


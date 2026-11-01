package com.sentinel.crier

import org.json.JSONObject

/** Validates authoritative broker identity and monotonic fills before any journal write. */
object OrderObservation {
 fun validate(order:JSONObject,client:String,symbol:String,side:String,quantity:Int?,previous:Int,expectedBroker:String="") {
  require(order.getString("id").isNotBlank() && (expectedBroker.isBlank() || order.getString("id")==expectedBroker)) { "Broker order ID changed" }
  require(quantity!=null && order.getString("client_order_id")==client && order.getString("symbol")==symbol && order.getString("side")==side && order.getString("qty").toBigDecimal()==quantity.toBigDecimal()) { "Broker order identity mismatch" }
  require(order.getString("status") in setOf("new","accepted","pending_new","accepted_for_bidding","partially_filled","filled","done_for_day","canceled","expired","replaced","pending_cancel","pending_replace","stopped","rejected","suspended","calculated")) { "Invalid broker status" }
  val filled=order.getString("filled_qty").toBigDecimal()
  if(!order.isNull("filled_avg_price") && order.has("filled_avg_price")) require(order.getString("filled_avg_price").toBigDecimal().signum()>0) { "Invalid broker fill price" }
  require(filled>=previous.toBigDecimal() && filled<=quantity.toBigDecimal() && filled.stripTrailingZeros().scale()<=0) { "Invalid cumulative fill" }
 }}

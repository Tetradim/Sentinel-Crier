package com.sentinel.crier
import kotlin.math.abs
object DiagnosticClock {
 data class Sample(val offset:Double,val uncertainty:Double,val sampledAt:Long)
 fun probe(before:Long,after:Long,rtt:Long,server:Long):Sample? =
  if(rtt<0 || abs((after-before)-rtt)>100) null else Sample(server-(before/2.0+after/2.0),rtt/2.0,after)
 fun latency(sender:Long,receiver:Long,so:Double,ro:Double,su:Double,ru:Double,ss:Long,rs:Long):Pair<Double,Double>? {
  if(sender-ss !in 0..60000 || receiver-rs !in 0..60000 || su !in 0.0..30000.0 || ru !in 0.0..30000.0 || !listOf(so,ro,su,ru).all { it.isFinite() }) return null
  val estimate=receiver+ro-sender-so; val uncertainty=su+ru
  return if(estimate < -uncertainty) null else Pair(estimate,uncertainty)
 }
}

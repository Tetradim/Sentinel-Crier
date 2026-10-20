package com.sentinel.crier
import java.math.BigDecimal
import java.math.RoundingMode
object Policy {
 fun price(source: String, mode: String, sell: Boolean, bps: Int, amount: String): String? {
  require(mode in setOf("exact_limit", "market", "bounded_limit"))
  val p = BigDecimal(source); require(p.signum() > 0 && bps in 0..10000 && BigDecimal(amount).signum() >= 0)
  if (mode == "market") return null
  if (mode == "exact_limit") return p.toPlainString()
  val delta = p.multiply(BigDecimal(bps)).divide(BigDecimal(10000)).min(BigDecimal(amount))
  return (if (sell) p.subtract(delta) else p.add(delta)).setScale(2, if (sell) RoundingMode.CEILING else RoundingMode.FLOOR).also { require(it.signum() > 0) }.toPlainString()
 }
 fun exitQuantity(requested: Int, filled: Int, sold: Int, holdings: Int) = minOf(requested, (filled-sold).coerceAtLeast(0), holdings.coerceAtLeast(0))
 fun canEnter(invalidated: Boolean, paused: Boolean, sequence: Int, newest: Int, age: Long, maxAge: Int) = !invalidated && !paused && sequence == newest && age in 0..maxAge.toLong()
}

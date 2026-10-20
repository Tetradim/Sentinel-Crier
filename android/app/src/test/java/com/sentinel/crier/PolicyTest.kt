package com.sentinel.crier
import org.junit.Assert.*
import org.junit.Test
import java.math.BigDecimal
class PolicyTest {
 @Test fun boundedBuyRoundsDown() { assertEquals("1.01", Policy.price("1.009", "bounded_limit", false, 100, "0.02")) }
 @Test fun boundedSellRoundsUp() { assertEquals("1.00", Policy.price("1.009", "bounded_limit", true, 100, "0.02")) }
 @Test fun exitNeverExceedsOwnershipOrHoldings() { assertEquals(2, Policy.exitQuantity(8, 3, 1, 9)); assertEquals(0, Policy.exitQuantity(8, 3, 3, 9)); assertEquals(1, Policy.exitQuantity(8, 3, 0, 1)) }
 @Test fun invalidationAlwaysBlocksEntry() { assertFalse(Policy.canEnter(true, false, 3, 3, 1, 10)); assertFalse(Policy.canEnter(false, false, 2, 3, 1, 10)); assertFalse(Policy.canEnter(false, false, 3, 3, 11, 10)) }
}

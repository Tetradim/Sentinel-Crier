package com.sentinel.crier
import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class EntryClockTest {
 @Test fun backwardSlewDoesNotExtendExpiryOrStartFutureWorkEarly() {
  var wall=Instant.parse("2026-01-01T00:00:00Z"); var mono=1000L
  val c=EntryClock({wall},{mono}); wall=wall.minusSeconds(1); mono+=1000
  val r=c.read()!!
  assertEquals(Instant.parse("2026-01-01T00:00:01Z"),r.effective)
  assertEquals(Instant.parse("2025-12-31T23:59:59Z"),r.wall)
 }
 @Test fun discontinuityAndBackwardsMonotonicTimeAreUncertain() {
  var wall=Instant.parse("2026-01-01T00:00:00Z"); var mono=1000L
  val c=EntryClock({wall},{mono}); wall=wall.plusSeconds(60); assertNull(c.read())
  wall=wall.minusSeconds(60); mono--; assertNull(c.read())
 }
}

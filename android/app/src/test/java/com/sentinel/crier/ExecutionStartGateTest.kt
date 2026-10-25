package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test

class ExecutionStartGateTest {
 @Test fun queuedStartCannotSurviveLogout() {
  val gate=ExecutionStartGate(); val ticket=gate.reserve()
  assertTrue(gate.active); gate.stop(true)
  assertFalse(gate.claim(ticket,Any(),true)); assertFalse(gate.active)
  try { gate.reserve(); fail("Logout must block starts") } catch(_:IllegalStateException) {}
  gate.finishLogout(); assertFalse(gate.claim(ticket,Any(),true))
  assertTrue(gate.claim(gate.reserve(),Any(),true))
 }
 @Test fun oldDrainDoesNotClearNewWorkerAndDisabledStartIsRejected() {
  val gate=ExecutionStartGate(); val old=Any(); val next=Any()
  assertTrue(gate.claim(gate.reserve(),old,true)); gate.stop()
  val ticket=gate.reserve(); assertFalse(gate.claim(ticket,next,false))
  assertTrue(gate.claim(ticket,next,true)); gate.drained(old); assertTrue(gate.active)
  gate.drained(next); assertFalse(gate.active)
 }
}

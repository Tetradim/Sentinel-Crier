package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.Executor

class ScopedReadTest {
 @Test fun observationRunsOffCallerAndDropsLateAccountOrLifecycleResult() {
  val work=mutableListOf<Runnable>(); val ui=mutableListOf<Runnable>()
  var current=true; var reads=0; var shown=""
  val read=ScopedRead(Executor { work.add(it) },Executor { ui.add(it) })
  read.load({ current },{ reads++; "old account" },{ shown=it },{ throw it })
  assertEquals(0,reads)
  work.removeAt(0).run(); current=false; ui.removeAt(0).run()
  assertEquals(1,reads); assertEquals("",shown)
 }
 @Test fun inactiveObservationNeverReadsAndErrorsAreDeliveredSafely() {
  val work=mutableListOf<Runnable>(); val ui=mutableListOf<Runnable>(); var error=""
  val read=ScopedRead(Executor { work.add(it) },Executor { ui.add(it) })
  read.load({ false },{ error("must not read") },{}, { throw it })
  work.removeAt(0).run(); assertTrue(ui.isEmpty())
  read.load({ true },{ throw IllegalArgumentException("stopped guidance") },{}, { error=it.message!! })
  work.removeAt(0).run(); ui.removeAt(0).run(); assertEquals("stopped guidance",error)
 }
}

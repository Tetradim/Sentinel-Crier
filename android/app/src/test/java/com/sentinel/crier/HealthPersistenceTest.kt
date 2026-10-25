package com.sentinel.crier

import org.junit.Assert.*
import org.junit.Test

class HealthPersistenceTest {
 @Test fun diskWorkIsDeferredAndOnlyTheLatestCompleteSnapshotIsWritten() {
  val tasks=mutableListOf<()->Unit>(); val saved=mutableListOf<String>(); val reports=mutableListOf<Boolean>()
  val p=HealthPersistence({saved.add(it); true},{reports.add(it)},{tasks.add(it)})
  p.enqueue("first"); p.enqueue("second"); p.enqueue("latest")
  assertTrue(saved.isEmpty()); assertEquals(1,tasks.size)
  tasks.removeAt(0)(); assertEquals(listOf("latest"),saved); assertEquals(listOf(true),reports)
 }
 @Test fun failuresAreReportedWithoutThrowingAndSubsequentWritesCanRecover() {
  val tasks=mutableListOf<()->Unit>(); val reports=mutableListOf<Boolean>(); var fail=true
  val p=HealthPersistence({if(fail) error("private storage failure"); true},{reports.add(it)},{tasks.add(it)})
  p.enqueue("one"); tasks.removeAt(0)(); assertEquals(listOf(false),reports)
  fail=false; p.enqueue("two"); tasks.removeAt(0)(); assertEquals(listOf(false,true),reports)
 }
}

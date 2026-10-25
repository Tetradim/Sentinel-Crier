package com.sentinel.crier
import java.time.Instant
import java.time.Duration

/** Detects local discontinuities; it does not synchronize clocks across devices. */
class EntryClock(private val wall:()->Instant={Instant.now()},private val mono:()->Long={System.nanoTime()/1000000}) {
 data class Reading(val effective:Instant,val wall:Instant)
 private val initialWall=wall()
 private val initialMono=mono()
 private var high=initialWall
 @Synchronized fun read():Reading? = runCatching {
  val current=wall(); val elapsed=Math.subtractExact(mono(),initialMono)
  if(elapsed<0 || kotlin.math.abs(Math.subtractExact(Duration.between(initialWall,current).toMillis(),elapsed))>5000) return null
  high=maxOf(high,current,initialWall.plusMillis(elapsed))
  Reading(high,current)
 }.getOrNull()
}

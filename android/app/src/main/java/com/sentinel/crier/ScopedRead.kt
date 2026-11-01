package com.sentinel.crier

import java.util.concurrent.Executor

/** Observations may wait for dispatch locks; only current-screen callbacks reach the UI. */
class ScopedRead(private val worker:Executor, private val ui:Executor) {
 fun <T> load(current:()->Boolean, read:()->T, show:(T)->Unit, failed:(Exception)->Unit) {
  worker.execute {
   if(!current()) return@execute
   val result=try { Result.success(read()) } catch(error:Exception) { Result.failure(error) }
   ui.execute {
    if(current()) result.fold(show) { failed(it as Exception) }
   }
  }
 }
}

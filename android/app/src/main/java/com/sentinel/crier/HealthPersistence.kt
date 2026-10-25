package com.sentinel.crier

/** Coalesced diagnostic snapshots; disk work runs only on the supplied executor. */
class HealthPersistence(private val save:(String)->Boolean,private val report:(Boolean)->Unit,private val execute:(()->Unit)->Unit) {
 private var pending:String?=null
 private var scheduled=false
 @Synchronized fun enqueue(value:String) {
  pending=value
  if(scheduled) return
  scheduled=true
  try { execute { drain() } } catch(_:Exception) { scheduled=false; runCatching { report(false) } }
 }
 private fun drain() {
  while(true) {
   val value=synchronized(this) { val next=pending; if(next==null) { scheduled=false; return }; pending=null; next }
   val okay=runCatching { save(value) }.getOrDefault(false)
   runCatching { report(okay) }
  }
 }
}

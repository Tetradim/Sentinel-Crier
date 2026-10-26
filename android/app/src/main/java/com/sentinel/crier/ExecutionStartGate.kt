package com.sentinel.crier

/** Process-local admission fence for queued starts and asynchronous worker drain. */
class ExecutionStartGate {
 private var epoch=0L
 private var pending:Long?=null
 private var blocked=false
 private val owners=mutableSetOf<Any>()
 private val admissions=mutableMapOf<Any,Long>()
 @Synchronized fun permits(owner:Any):Boolean = !blocked && owner in owners && admissions[owner]==epoch
 val active:Boolean @Synchronized get()=pending!=null || owners.isNotEmpty()
 val closing:Boolean @Synchronized get()=blocked
 @Synchronized fun reserve():Long { check(!blocked) { "Sign out is still stopping workers" }; return pending ?: (++epoch).also { pending=it } }
 @Synchronized fun abandon(ticket:Long) { if(pending==ticket) pending=null }
 @Synchronized fun claim(ticket:Long,owner:Any,enabled:Boolean):Boolean {
  if(blocked || !enabled || pending!=ticket) return false
  pending=null; owners.add(owner); admissions[owner]=ticket; return true
 }
 @Synchronized fun stop(forLogout:Boolean=false) { epoch++; pending=null; if(forLogout) blocked=true }
 @Synchronized fun drained(owner:Any) { owners.remove(owner); admissions.remove(owner) }
 @Synchronized fun finishLogout() { check(owners.isEmpty()); epoch++; pending=null; blocked=false }
}

package com.sentinel.crier

import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import org.json.JSONObject

/** A coalesced signal retains work arriving while the consumer is busy. */
class WorkSignal {
 private val monitor=Object()
 private var pending=false
 fun wake() = synchronized(monitor) { pending=true; monitor.notifyAll() }
 fun await(milliseconds:Long) = synchronized(monitor) { if(!pending) monitor.wait(milliseconds); pending=false }
}
object JournalWakes { val execution=WorkSignal(); val outbox=WorkSignal(); val telemetry=WorkSignal() }

object EventStreamParser {
 const val MAX_BYTES=1048576
 fun read(input:InputStream, active:()->Boolean={true}, receive:(String,JSONObject)->Unit) {
  var bytes=0; var lines=0; var name="message"; val data=StringBuilder(); val line=ByteArrayOutputStream()
  fun decode():String = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(line.toByteArray())).toString().removeSuffix("\r")
  while(active()) {
   val b=input.read(); if(b<0) { require(line.size()==0 && data.isEmpty()) { "Incomplete SSE frame" }; return }
   bytes++; require(bytes<=MAX_BYTES) { "SSE frame too large" }
   if(b!=10) { line.write(b); continue }
   val text=decode(); line.reset(); lines++; require(lines<=8192) { "Too many SSE lines" }
   if(text.isEmpty()) {
    if(name in setOf("ready","events","dashboard","heartbeat")) { require(data.isNotEmpty()) { "Missing SSE payload" }; receive(name,JSONObject(data.toString().removeSuffix("\n"))) }
    bytes=0; lines=0; name="message"; data.setLength(0)
   } else if(!text.startsWith(":")) {
    val field=text.substringBefore(':'); val value=text.substringAfter(':',"").removePrefix(" ")
    if(field=="event") name=value
    if(field=="data") data.append(value).append('\n')
   }
  }
 }
}
class PushConnection(private val open:(URI)->HttpURLConnection={ it.toURL().openConnection() as HttpURLConnection }) {
 @Volatile private var connection:HttpURLConnection?=null
 @Volatile private var closed=false
 fun close() { closed=true; connection?.disconnect() }
 fun read(url:String,headers:Map<String,String>,active:()->Boolean,receive:(String,JSONObject)->Unit) {
  check(!closed); val uri=URI(url); require(uri.scheme=="https" && uri.userInfo==null)
  val c=open(uri); connection=c
  try {
   c.instanceFollowRedirects=false; c.connectTimeout=15000; c.readTimeout=25000
   c.setRequestProperty("Accept","text/event-stream"); headers.forEach { (k,v)->c.setRequestProperty(k,v) }
   check(!closed && active()); if(c.responseCode !in 200..299) throw HttpError(c.responseCode)
   require(c.contentType?.substringBefore(';')?.trim()=="text/event-stream") { "Streaming unavailable" }
   val started=System.nanoTime(); var greeted=false
   c.inputStream.use { EventStreamParser.read(it,{!closed && active()}) { event,body -> if(event=="ready") greeted=true; receive(event,body) } }
   check(greeted && System.nanoTime()-started>=1000000000L) { "Stream ended before a stable connection" }
  } finally { c.disconnect(); connection=null }
 }
}

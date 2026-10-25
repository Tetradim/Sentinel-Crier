package com.sentinel.crier
import org.json.JSONObject

data class PracticeStep(val title:String,val body:String)
data class PracticeJourney(val id:String,val title:String,val steps:List<PracticeStep>)
data class PracticeGuide(val notice:String,val privacy:String,val journeys:List<PracticeJourney>) {
 fun format(id:String):String {
  val journey=journeys.first { it.id==id }
  return (listOf(notice,journey.title)+journey.steps.flatMapIndexed { i,step -> listOf("${i+1}. ${step.title}",step.body) }+privacy).joinToString("\n\n")
 }
 companion object {
  const val SUPPORT="https://github.com/Tetradim/Sentinel-Crier/issues"
  private fun keys(value:JSONObject,expected:Set<String>) { require(value.keys().asSequence().toSet()==expected) { "Invalid practice guide fields" } }
  private fun text(value:JSONObject,key:String,limit:Int):String {
   val result=value.get(key); require(result is String && result.isNotBlank() && result.length<=limit && result.none { it.code<32 }) { "Invalid practice text" }; return result
  }
  fun parse(source:String):PracticeGuide {
   val root=JSONObject(source); keys(root,setOf("version","notice","privacy","journeys"))
   require(root.get("version") is Int && root.getInt("version")==1) { "Unsupported practice guide" }
   val values=root.getJSONArray("journeys"); require(values.length()==3)
   val journeys=(0 until values.length()).map { index ->
    val journey=values.getJSONObject(index); keys(journey,setOf("id","title","steps"))
    val id=text(journey,"id",100); require(id in setOf("alerts","trade","follow"))
    val steps=journey.getJSONArray("steps"); require(steps.length() in 3..8)
    PracticeJourney(id,text(journey,"title",100),(0 until steps.length()).map { i ->
     val step=steps.getJSONObject(i); keys(step,setOf("title","body"))
     PracticeStep(text(step,"title",100),text(step,"body",1200))
    })
   }
   require(journeys.map { it.id }.toSet()==setOf("alerts","trade","follow"))
   return PracticeGuide(text(root,"notice",1200),text(root,"privacy",1200),journeys)
  }
 }
}

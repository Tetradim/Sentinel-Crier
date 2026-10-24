package com.sentinel.crier

/** Labels are presentation only; values are the unchanged persisted protocol. */
data class SetupOption(val value:String, val label:String)
class SetupChoiceSet(val options:List<SetupOption>) {
 fun forSaved(saved:String):SetupSelection {
  val index=options.indexOfFirst { it.value==saved }
  return if(index>=0) SetupSelection(options,index) else SetupSelection(listOf(SetupOption(saved,"Choose a valid option · saved: ${saved.ifBlank { "(blank)" }}"))+options,0,true)
 }
}
class SetupSelection(private val options:List<SetupOption>, val selectedIndex:Int, private val invalidFirst:Boolean=false) {
 val labels:List<String> get()=options.map { it.label }
 fun valueAt(index:Int):String=options[index].value
 fun requireValue(index:Int):String { require(!(invalidFirst && index==0)) { "Choose a valid option before continuing" }; return valueAt(index) }
}
object SetupChoices {
 val environment=SetupChoiceSet(listOf(SetupOption("paper","Paper · simulated funds"),SetupOption("live","Live · real funds")))
 val pricing=SetupChoiceSet(listOf(SetupOption("exact_limit","Exact limit · source price"),SetupOption("bounded_limit","Bounded limit · configured slippage"),SetupOption("market","Market · no price limit")))
 val format=SetupChoiceSet(listOf(SetupOption("card","Card · rich message"),SetupOption("plain","Plain text")))
 val instrument=SetupChoiceSet(listOf(SetupOption("stock","Stock"),SetupOption("option","Option · standard contract")))
}

package com.sentinel.crier

/** Preparation only; no installed deep-link handler, login or credential installation.
 * Pass raw URI text, never normalized/decoded text. No return enables execution.
 */
object OAuthReturn {
    private const val prefix = "sentinelcrier://oauth/complete?flow="
    private val flowPattern = Regex("[A-Za-z0-9_-]{43}")
    fun validFlow(flow: String) = flow.length == 43 && flowPattern.matches(flow)
    fun parse(uri: String): String? {
        if (uri.length != prefix.length + 43 || !uri.startsWith(prefix)) return null
        return uri.substring(prefix.length).takeIf(::validFlow)
    }
    fun matchPending(pending: PendingOAuthReturn?, uri: String, expectedFlow: String,
                     expectedContext: OAuthReturnContext, now: Double): OAuthReturnContext? =
        pending?.matchReturn(uri, expectedFlow, expectedContext, now)
}

data class OAuthReturnContext(val owner: String, val provider: String,
                              val environment: String, val purpose: String) {
    init {
        require(owner.isNotBlank() && owner.length <= 256)
        require(provider in setOf("alpaca", "discord"))
        require(environment in setOf("paper", "live"))
        require(purpose in setOf("alerts", "trade"))
        require(provider != "discord" || purpose == "alerts")
    }
}

/** Memory only. Caller supplies a trusted consistent clock and clears pending on
 * logout/session changes. Acceptance yields local context for a future authenticated
 * redemption integration, never credentials or consent to execute/publish.
 */
class PendingOAuthReturn(private val flow: String, private val context: OAuthReturnContext,
                         private val expiresAt: Double) {
    private var active = true
    init { require(OAuthReturn.validFlow(flow) && expiresAt.isFinite()) }
    @Synchronized fun invalidate() { active = false }
    @Synchronized fun cancel() { active = false }
    @Synchronized fun matchReturn(uri: String, expectedFlow: String,
                                 expectedContext: OAuthReturnContext, now: Double): OAuthReturnContext? {
        if (!active) return null
        if (!now.isFinite() || now >= expiresAt) { active = false; return null }
        if (expectedFlow != flow || expectedContext != context || OAuthReturn.parse(uri) != flow) return null
        active = false
        return context
    }
}

package com.sentinel.crier

import java.io.File
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class OAuthReturnTest {
    private fun fixture(): JSONObject {
        val stream = javaClass.classLoader?.getResourceAsStream("oauth-return.json")
        return JSONObject(stream?.bufferedReader()?.use { it.readText() }
            ?: File("tests/fixtures/oauth-return.json").readText())
    }
    private val context = OAuthReturnContext("owner-1", "alpaca", "paper", "alerts")
    private fun pending(flow: String) = PendingOAuthReturn(flow, context, 100.0)

    @Test fun sharedCanonicalContract() {
        val f = fixture(); val cases = f.getJSONArray("cases")
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            assertEquals(c.getString("name"), if (c.getBoolean("valid")) f.getString("flow") else null,
                OAuthReturn.parse(c.getString("uri")))
        }
    }
    @Test fun onlyTrustedContextCanMatchAndOnlyOnce() {
        val f = fixture(); val flow = f.getString("flow"); val uri = f.getString("canonical")
        val p = pending(flow)
        for (wrong in listOf(context.copy(owner = "owner-2"), context.copy(provider = "discord"),
            context.copy(environment = "live"), context.copy(purpose = "trade"))) {
            assertNull(p.matchReturn(uri, flow, wrong, 1.0))
        }
        assertNull(p.matchReturn(uri, "B".repeat(43), context, 1.0))
        assertNull(p.matchReturn(uri.replace(flow, "B".repeat(43)), flow, context, 1.0))
        assertNull(p.matchReturn("$uri&code=secret", flow, context, 1.0))
        assertSame(context, p.matchReturn(uri, flow, context, 99.0))
        assertNull(p.matchReturn(uri, flow, context, 99.0))
    }
    @Test fun cancellationExpirationInvalidationAndRestartRejectReturns() {
        val f = fixture(); val flow = f.getString("flow"); val uri = f.getString("canonical")
        for (action in listOf("cancel", "invalidate", "timeout", "nonfinite")) {
            val p = pending(flow)
            when (action) {
                "cancel" -> p.cancel()
                "invalidate" -> p.invalidate()
                "timeout" -> assertNull(p.matchReturn(uri, flow, context, 100.0))
                else -> assertNull(p.matchReturn(uri, flow, context, Double.NaN))
            }
            assertNull(action, p.matchReturn(uri, flow, context, 1.0))
        }
        assertNull(OAuthReturn.matchPending(null, uri, flow, context, 1.0))
        assertTrue(runCatching { PendingOAuthReturn("short", context, 100.0) }.isFailure)
        assertTrue(runCatching { PendingOAuthReturn(flow, context, Double.POSITIVE_INFINITY) }.isFailure)
        assertTrue(runCatching { context.copy(provider = "discord", purpose = "trade") }.isFailure)
    }
    @Test fun concurrentReplayAcceptsAtMostOnce() {
        val f = fixture(); val flow = f.getString("flow"); val p = pending(flow)
        val accepted = java.util.concurrent.atomic.AtomicInteger()
        val threads = (1..12).map { Thread {
            if (p.matchReturn(f.getString("canonical"), flow, context, 1.0) != null) accepted.incrementAndGet()
        } }
        threads.forEach { it.start() }; threads.forEach { it.join() }
        assertEquals(1, accepted.get())
    }
}

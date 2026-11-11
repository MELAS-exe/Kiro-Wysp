package dev.wysp.intellij.rpc

import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.WyspError
import dev.wysp.intellij.json.Json
import dev.wysp.intellij.json.obj
import dev.wysp.intellij.json.str
import java.net.URI
import java.net.http.HttpClient
import java.net.http.WebSocket
import java.time.Duration
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CompletionException
import java.util.concurrent.CompletionStage
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.logging.Logger

/**
 * JSON-RPC 2.0 client of the Wysp Core (`/ws/adapter`): `wysp.hello` first, heartbeats, reconnection with
 * backoff. Requests from the Core go to [handler], which returns a future completed on any thread; the reply
 * is sent when it completes. Sends are serialised on one thread (java.net.http allows one pending send).
 */
class RpcClient(
    private val url: () -> String,
    private val hello: () -> Map<String, Any?>, // {manifest, token}
    private val handler: (method: String, params: Map<String, Any?>) -> CompletableFuture<Any?>,
    private val stateVersion: () -> Long,
    private val onStatus: (status: String, detail: String?) -> Unit,
) {
    private val log = Logger.getLogger("wysp.rpc")
    private val sender = Executors.newSingleThreadExecutor { r -> Thread(r, "wysp-send").apply { isDaemon = true } }
    private val timer = Executors.newSingleThreadScheduledExecutor { r -> Thread(r, "wysp-timer").apply { isDaemon = true } }
    private val http: HttpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()

    @Volatile private var ws: WebSocket? = null
    @Volatile private var running = false
    @Volatile private var generation = 0 // bumps on each connect/stop so stale callbacks are ignored
    @Volatile var status: String = "stopped"
        private set
    @Volatile var lastError: String? = null
        private set
    @Volatile var sessionId: String? = null
        private set
    private var backoffMs = 500L
    private var heartbeat: ScheduledFuture<*>? = null
    private var heartbeatS = 15L

    val connected: Boolean get() = status == "connected"

    @Synchronized
    fun start() {
        if (running) return
        running = true
        connect(++generation)
    }

    @Synchronized
    fun stop() {
        running = false
        generation++
        heartbeat?.cancel(false)
        val socket = ws
        ws = null
        if (socket != null) {
            send(socket, mapOf("jsonrpc" to "2.0", "method" to "wysp.bye", "params" to mapOf("reason" to "stop")))
            sender.execute { runCatching { socket.sendClose(WebSocket.NORMAL_CLOSURE, "bye").get(2, TimeUnit.SECONDS) } }
        }
        setStatus("stopped", null)
    }

    /** A notification; safe from any thread. Dropped when not connected. */
    fun notify(method: String, params: Map<String, Any?>) {
        val socket = ws ?: return
        if (!connected) return
        send(socket, mapOf("jsonrpc" to "2.0", "method" to method, "params" to params))
    }

    fun dispose() {
        stop()
        timer.shutdownNow()
        sender.shutdown()
    }

    // ---------------------------------------------------------------------------------------- connection
    private fun connect(gen: Int) {
        if (!running || gen != generation) return
        setStatus("connecting", null)
        val target = try {
            URI(url())
        } catch (e: Exception) {
            fail(gen, "bad Core URL: ${e.message}")
            return
        }
        // The Core listens on this machine only, and the pairing token travels in the hello: never send it away.
        if (target.host !in LOOPBACK) {
            running = false
            lastError = "the Core URL must point to this machine (127.0.0.1 or localhost), not ${target.host}"
            setStatus("refused", lastError)
            return
        }
        http.newWebSocketBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .buildAsync(target, Listener(gen))
            .whenComplete { socket, err ->
                if (err != null) {
                    fail(gen, "cannot reach Core at $target: ${rootMessage(err)}")
                    return@whenComplete
                }
                synchronized(this) {
                    if (gen != generation || !running) {
                        socket.abort()
                        return@whenComplete
                    }
                    ws = socket
                }
                send(socket, mapOf("jsonrpc" to "2.0", "id" to HELLO_ID, "method" to "wysp.hello", "params" to hello()))
            }
    }

    private fun fail(gen: Int, error: String) {
        synchronized(this) {
            if (gen != generation) return
            ws = null
            heartbeat?.cancel(false)
            sessionId = null
            lastError = error
            if (status != "refused") setStatus("disconnected", error)
            if (!running) return
            val delay = backoffMs
            backoffMs = minOf(backoffMs * 2, 10_000L)
            val next = ++generation
            timer.schedule({ connect(next) }, delay, TimeUnit.MILLISECONDS)
        }
    }

    private fun setStatus(s: String, detail: String?) {
        if (s == status && detail == null) return
        status = s
        runCatching { onStatus(s, detail) }
    }

    // ------------------------------------------------------------------------------------------- sending
    private fun send(socket: WebSocket, message: Map<String, Any?>) {
        val text = Json.write(message)
        sender.execute {
            try {
                socket.sendText(text, true).get(10, TimeUnit.SECONDS)
            } catch (e: Exception) {
                log.fine("send failed: ${rootMessage(e)}")
            }
        }
    }

    // ------------------------------------------------------------------------------------------- inbound
    private fun onMessage(gen: Int, socket: WebSocket, text: String) {
        if (gen != generation) return
        val msg = try {
            Json.parseObject(text)
        } catch (_: Exception) {
            return
        }
        val method = msg.str("method")
        if (method != null) {
            onRequest(socket, method, msg["id"], msg["params"].obj())
            return
        }
        if (msg["id"] == HELLO_ID) {
            val err = msg["error"]
            if (err != null) {
                val e = err.obj()
                lastError = "hello refused (${e["code"]}): ${e["message"]}"
                setStatus("refused", lastError)
                running = false // a refused hello (bad token, wrong version) will not fix itself
                socket.sendClose(WebSocket.NORMAL_CLOSURE, "refused")
                return
            }
            val result = msg["result"].obj()
            sessionId = result.str("session_id")
            heartbeatS = minOf(15L, ((result["heartbeat_interval_s"] as? Number)?.toLong() ?: 20L).coerceAtLeast(2L))
            backoffMs = 500L
            lastError = null
            setStatus("connected", null)
            synchronized(this) {
                heartbeat?.cancel(false)
                heartbeat = timer.scheduleAtFixedRate({
                    if (gen == generation) notify("wysp.heartbeat", mapOf("state_version" to stateVersion()))
                }, heartbeatS, heartbeatS, TimeUnit.SECONDS)
            }
        }
    }

    private fun onRequest(socket: WebSocket, method: String, id: Any?, params: Map<String, Any?>) {
        val future = try {
            handler(method, params)
        } catch (e: Throwable) {
            CompletableFuture.failedFuture(e)
        }
        future.whenComplete { result, err ->
            if (id == null) return@whenComplete
            if (err == null) {
                send(socket, mapOf("jsonrpc" to "2.0", "id" to id, "result" to result))
            } else {
                val cause = unwrap(err)
                val error = if (cause is WyspError) {
                    cause.toJson()
                } else {
                    log.warning("handler $method failed: ${cause::class.java.simpleName}: ${cause.message}")
                    mapOf("code" to ErrorCode.EXECUTION_FAILED, "message" to "${cause::class.java.simpleName}: ${cause.message}")
                }
                send(socket, mapOf("jsonrpc" to "2.0", "id" to id, "error" to error))
            }
        }
    }

    private inner class Listener(private val gen: Int) : WebSocket.Listener {
        private val buffer = StringBuilder()

        override fun onOpen(webSocket: WebSocket) {
            webSocket.request(1)
        }

        override fun onText(webSocket: WebSocket, data: CharSequence, last: Boolean): CompletionStage<*>? {
            buffer.append(data)
            if (last) {
                val text = buffer.toString()
                buffer.setLength(0)
                onMessage(gen, webSocket, text)
            }
            webSocket.request(1)
            return null
        }

        override fun onClose(webSocket: WebSocket, statusCode: Int, reason: String): CompletionStage<*>? {
            fail(gen, "closed by Core ($statusCode${if (reason.isNotEmpty()) ": $reason" else ""})")
            return null
        }

        override fun onError(webSocket: WebSocket, error: Throwable) {
            fail(gen, "connection error: ${rootMessage(error)}")
        }
    }

    companion object {
        const val HELLO_ID = "hello-1"
        val LOOPBACK = setOf("127.0.0.1", "localhost", "[::1]", "::1")

        fun unwrap(e: Throwable): Throwable {
            var t = e
            while ((t is CompletionException || t is java.util.concurrent.ExecutionException) && t.cause != null) t = t.cause!!
            return t
        }

        fun rootMessage(e: Throwable): String {
            var t = e
            while (t.cause != null && t.cause !== t) t = t.cause!!
            return t.message ?: t::class.java.simpleName
        }
    }
}

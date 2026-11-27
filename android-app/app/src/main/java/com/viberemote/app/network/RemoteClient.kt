package com.viberemote.app.network

import com.viberemote.app.model.ConnectionConfig
import com.viberemote.app.model.DiscoveredHost
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.util.Locale
import java.util.concurrent.TimeUnit

enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
}

data class ServerStatus(
    val connectionState: ConnectionState = ConnectionState.DISCONNECTED,
    val asrReady: Boolean = false,
    val asrError: String? = null,
    val llmPolishAvailable: Boolean = false,
    val voiceState: String = "idle", // idle, recording, transcribing, error
    val statusMessage: String = "未连接电脑",
    val lastTranscript: String = "",
    val lastLatencyMs: Int = 0,
    val history: List<String> = emptyList(),
)

class RemoteClient(
    private val scope: CoroutineScope,
    private val onTranscriptPasted: (String) -> Unit,
    private val onServerError: (String) -> Unit,
) {
    private val okHttp = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private val _status = MutableStateFlow(ServerStatus())
    val status: StateFlow<ServerStatus> = _status.asStateFlow()

    @Volatile
    private var activeConfig: ConnectionConfig? = null

    @Volatile
    private var webSocket: WebSocket? = null

    @Volatile
    private var udpSocket: DatagramSocket? = null

    @Volatile
    private var cachedUdpAddress: InetAddress? = null

    @Volatile
    private var manualDisconnect: Boolean = false

    private var reconnectJob: Job? = null
    private var heartbeatJob: Job? = null

    fun connect(config: ConnectionConfig) {
        if (!config.isValid) {
            _status.value = _status.value.copy(
                connectionState = ConnectionState.DISCONNECTED,
                statusMessage = "请先扫码或配置电脑 IP 与配对码",
            )
            return
        }
        manualDisconnect = false
        activeConfig = config
        reconnectJob?.cancel()
        closeSocketsOnly()

        scope.launch(Dispatchers.IO) {
            cachedUdpAddress = runCatching { InetAddress.getByName(config.host) }.getOrNull()
            udpSocket = runCatching { DatagramSocket() }.getOrNull()
        }

        openWebSocket(config)
    }

    fun disconnect() {
        manualDisconnect = true
        reconnectJob?.cancel()
        heartbeatJob?.cancel()
        closeSocketsOnly()
        _status.value = _status.value.copy(
            connectionState = ConnectionState.DISCONNECTED,
            voiceState = "idle",
            statusMessage = "已手动断开",
        )
    }

    private fun closeSocketsOnly() {
        webSocket?.close(1000, "reconnect")
        webSocket = null
        udpSocket?.close()
        udpSocket = null
    }

    private fun openWebSocket(config: ConnectionConfig) {
        _status.value = _status.value.copy(
            connectionState = ConnectionState.CONNECTING,
            statusMessage = "正在连接 ${config.host}:${config.wsPort}...",
        )

        val request = Request.Builder().url(config.wsUrl()).build()
        webSocket = okHttp.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _status.value = _status.value.copy(
                    connectionState = ConnectionState.CONNECTED,
                    statusMessage = "已连接 ${config.host}",
                )
                startHeartbeat()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleServerJson(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                heartbeatJob?.cancel()
                val errMsg = if (code == 4001) "配对码 Token 错误，请重新扫码" else "连接已断开"
                _status.value = _status.value.copy(
                    connectionState = ConnectionState.DISCONNECTED,
                    voiceState = "idle",
                    statusMessage = errMsg,
                )
                if (!manualDisconnect && code != 4001) {
                    scheduleReconnect()
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                heartbeatJob?.cancel()
                _status.value = _status.value.copy(
                    connectionState = ConnectionState.DISCONNECTED,
                    voiceState = "idle",
                    statusMessage = "连接失败，重试中...",
                )
                if (!manualDisconnect) {
                    scheduleReconnect()
                }
            }
        })
    }

    private fun startHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = scope.launch(Dispatchers.IO) {
            while (isActive) {
                delay(8000)
                sendJson(JSONObject().put("type", "ping"))
            }
        }
    }

    private fun scheduleReconnect() {
        reconnectJob?.cancel()
        val cfg = activeConfig ?: return
        reconnectJob = scope.launch(Dispatchers.IO) {
            delay(2000)
            if (!manualDisconnect) {
                openWebSocket(cfg)
            }
        }
    }

    private fun handleServerJson(raw: String) {
        val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return
        when (obj.optString("type")) {
            "hello" -> {
                val asrReady = obj.optBoolean("asr_ready", false)
                val asrErr = obj.optString("asr_error").takeIf { it.isNotBlank() && it != "null" }
                val llmEnabled = obj.optBoolean("llm_polish_enabled", false)
                _status.value = _status.value.copy(
                    asrReady = asrReady,
                    asrError = asrErr,
                    llmPolishAvailable = llmEnabled,
                    statusMessage = if (asrReady) "已连接 · SenseVoice 就绪" else "已连接 · 模型加载中...",
                )
            }

            "pong" -> {
                val asrReady = obj.optBoolean("asr_ready", _status.value.asrReady)
                if (asrReady != _status.value.asrReady) {
                    _status.value = _status.value.copy(
                        asrReady = asrReady,
                        statusMessage = if (asrReady) "已连接 · SenseVoice 就绪" else _status.value.statusMessage,
                    )
                }
            }

            "status" -> {
                val state = obj.optString("state", "idle")
                val msg = obj.optString("message", "")
                _status.value = _status.value.copy(
                    voiceState = state,
                    statusMessage = msg.ifBlank { _status.value.statusMessage },
                )
                if (state == "error") {
                    onServerError(msg)
                }
            }

            "transcript" -> {
                val finalText = obj.optString("final_text", "")
                val latency = obj.optInt("latency_ms", 0)
                val updatedHistory = if (finalText.isNotBlank()) {
                    (listOf(finalText) + _status.value.history.filterNot { it == finalText }).take(10)
                } else {
                    _status.value.history
                }
                _status.value = _status.value.copy(
                    voiceState = "idle",
                    lastTranscript = finalText,
                    lastLatencyMs = latency,
                    history = updatedHistory,
                    statusMessage = if (latency > 0) "已上屏 (${latency}ms)" else "已上屏",
                )
                if (finalText.isNotBlank()) {
                    onTranscriptPasted(finalText)
                }
            }
        }
    }

    fun sendMouseMove(dx: Float, dy: Float) {
        val cfg = activeConfig ?: return
        if (dx == 0f && dy == 0f) return
        val payload = String.format(Locale.US, "M|%s|%.2f|%.2f", cfg.token, dx, dy)
        sendUdpOrFallback(payload) {
            sendJson(JSONObject().put("type", "move").put("dx", dx.toDouble()).put("dy", dy.toDouble()))
        }
    }

    fun sendScroll(dx: Float, dy: Float) {
        val cfg = activeConfig ?: return
        if (dx == 0f && dy == 0f) return
        val payload = String.format(Locale.US, "W|%s|%.2f|%.2f", cfg.token, dx, dy)
        sendUdpOrFallback(payload) {
            sendJson(JSONObject().put("type", "scroll").put("dx", dx.toDouble()).put("dy", dy.toDouble()))
        }
    }

    private fun sendUdpOrFallback(payload: String, fallback: () -> Unit) {
        val cfg = activeConfig ?: return
        val sock = udpSocket
        val addr = cachedUdpAddress
        if (sock == null || addr == null || sock.isClosed) {
            fallback()
            return
        }
        scope.launch(Dispatchers.IO) {
            runCatching {
                val bytes = payload.toByteArray(Charsets.UTF_8)
                sock.send(DatagramPacket(bytes, bytes.size, addr, cfg.udpPort))
            }
        }
    }

    fun sendClick(button: String = "left", action: String = "click") {
        sendJson(JSONObject().put("type", "click").put("button", button).put("action", action))
    }

    fun sendKeys(keys: List<String>) {
        val arr = JSONArray()
        keys.forEach { arr.put(it) }
        sendJson(JSONObject().put("type", "key").put("keys", arr))
    }

    fun sendText(text: String, autoEnter: Boolean) {
        if (text.isBlank()) return
        sendJson(JSONObject().put("type", "text").put("text", text).put("auto_enter", autoEnter))
    }

    fun sendAudioStart(sampleRate: Int = 16000, autoEnter: Boolean, polish: Boolean) {
        sendJson(
            JSONObject()
                .put("type", "audio_start")
                .put("sample_rate", sampleRate)
                .put("auto_enter", autoEnter)
                .put("polish", polish)
        )
    }

    fun sendAudioChunk(pcmBytes: ByteArray) {
        webSocket?.send(pcmBytes.toByteString(0, pcmBytes.size))
    }

    fun sendAudioEnd() {
        sendJson(JSONObject().put("type", "audio_end"))
    }

    fun sendAudioCancel() {
        sendJson(JSONObject().put("type", "audio_cancel"))
    }

    private fun sendJson(obj: JSONObject) {
        webSocket?.send(obj.toString())
    }

    suspend fun discoverLanServers(udpPort: Int = 8766, timeoutMs: Int = 1200): List<DiscoveredHost> =
        withContext(Dispatchers.IO) {
            val found = linkedMapOf<String, DiscoveredHost>()
            var sock: DatagramSocket? = null
            try {
                sock = DatagramSocket()
                sock.broadcast = true
                sock.soTimeout = 350
                val probe = "DISCOVER".toByteArray(Charsets.UTF_8)
                val broadcastAddr = InetAddress.getByName("255.255.255.255")
                sock.send(DatagramPacket(probe, probe.size, broadcastAddr, udpPort))

                val deadline = System.currentTimeMillis() + timeoutMs
                val buf = ByteArray(256)
                while (System.currentTimeMillis() < deadline) {
                    val pkt = DatagramPacket(buf, buf.size)
                    try {
                        sock.receive(pkt)
                        val reply = String(pkt.data, 0, pkt.length, Charsets.UTF_8).trim()
                        val parts = reply.split("|")
                        if (parts.size >= 4 && parts[0] == "VIBEREMOTE") {
                            val ip = pkt.address.hostAddress ?: continue
                            val wsPort = parts[1].toIntOrNull() ?: 8765
                            val uPort = parts[2].toIntOrNull() ?: udpPort
                            val hostname = parts[3]
                            found[ip] = DiscoveredHost(ip, wsPort, uPort, hostname)
                        }
                    } catch (_: SocketTimeoutException) {
                        // continue until deadline
                    }
                }
            } catch (_: Exception) {
                // ignore network error
            } finally {
                sock?.close()
            }
            found.values.toList()
        }
}

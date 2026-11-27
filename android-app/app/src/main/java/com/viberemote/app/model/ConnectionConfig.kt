package com.viberemote.app.model

import android.content.Context
import android.net.Uri

data class ConnectionConfig(
    val host: String = "",
    val wsPort: Int = 8765,
    val udpPort: Int = 8766,
    val token: String = "",
    val sensitivity: Float = 1.6f,
    val naturalScroll: Boolean = true,
    val autoEnter: Boolean = true,
    val llmPolish: Boolean = false,
    val volumeKeyBlindMode: Boolean = true,
    val volumeUpAction: VolumeUpAction = VolumeUpAction.ENTER,
) {
    val isValid: Boolean
        get() = host.isNotBlank() && wsPort in 1..65535 && udpPort in 1..65535 && token.isNotBlank()

    fun wsUrl(): String = "ws://$host:$wsPort/ws?token=${Uri.encode(token)}"

    companion object {
        fun fromQrUri(raw: String): ConnectionConfig? {
            val uri = runCatching { Uri.parse(raw.trim()) }.getOrNull() ?: return null
            if (uri.scheme != "viberemote" || uri.host != "connect") return null
            val host = uri.getQueryParameter("host")?.trim().orEmpty()
            val wsPort = uri.getQueryParameter("port")?.toIntOrNull() ?: 8765
            val udpPort = uri.getQueryParameter("udp")?.toIntOrNull() ?: 8766
            val token = uri.getQueryParameter("token")?.trim().orEmpty()
            if (host.isBlank() || token.isBlank()) return null
            return ConnectionConfig(
                host = host,
                wsPort = wsPort,
                udpPort = udpPort,
                token = token,
            )
        }
    }
}

enum class VolumeUpAction(val label: String, val keys: List<String>) {
    ENTER("Enter 发送", listOf("enter")),
    UNDO("Ctrl+Z 撤销", listOf("ctrl", "z")),
    TAB("Tab 补全", listOf("tab")),
    ESC("Esc 取消", listOf("esc")),
}

data class DiscoveredHost(
    val host: String,
    val wsPort: Int,
    val udpPort: Int,
    val hostname: String,
)

class ConfigStore(context: Context) {
    private val prefs = context.getSharedPreferences("viberemote_prefs", Context.MODE_PRIVATE)

    fun load(): ConnectionConfig {
        val actionName = prefs.getString("volume_up_action", VolumeUpAction.ENTER.name)
        val action = VolumeUpAction.entries.firstOrNull { it.name == actionName } ?: VolumeUpAction.ENTER
        return ConnectionConfig(
            host = prefs.getString("host", "").orEmpty(),
            wsPort = prefs.getInt("ws_port", 8765),
            udpPort = prefs.getInt("udp_port", 8766),
            token = prefs.getString("token", "").orEmpty(),
            sensitivity = prefs.getFloat("sensitivity", 1.6f),
            naturalScroll = prefs.getBoolean("natural_scroll", true),
            autoEnter = prefs.getBoolean("auto_enter", true),
            llmPolish = prefs.getBoolean("llm_polish", false),
            volumeKeyBlindMode = prefs.getBoolean("volume_blind", true),
            volumeUpAction = action,
        )
    }

    fun save(config: ConnectionConfig) {
        prefs.edit()
            .putString("host", config.host)
            .putInt("ws_port", config.wsPort)
            .putInt("udp_port", config.udpPort)
            .putString("token", config.token)
            .putFloat("sensitivity", config.sensitivity)
            .putBoolean("natural_scroll", config.naturalScroll)
            .putBoolean("auto_enter", config.autoEnter)
            .putBoolean("llm_polish", config.llmPolish)
            .putBoolean("volume_blind", config.volumeKeyBlindMode)
            .putString("volume_up_action", config.volumeUpAction.name)
            .apply()
    }
}

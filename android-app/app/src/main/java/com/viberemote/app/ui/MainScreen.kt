package com.viberemote.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.viberemote.app.model.ConnectionConfig
import com.viberemote.app.model.DiscoveredHost
import com.viberemote.app.network.ConnectionState
import com.viberemote.app.network.ServerStatus

@Composable
fun MainScreen(
    config: ConnectionConfig,
    status: ServerStatus,
    isRecording: Boolean,
    waitingEditTranscript: Boolean,
    pendingEditText: String?,
    stealthMode: Boolean,
    onToggleStealth: () -> Unit,
    onToggleAutoEnter: () -> Unit,
    onToggleLlmPolish: () -> Unit,
    onOpenConfig: () -> Unit,
    showConnectDialog: Boolean,
    onDismissConnectDialog: () -> Unit,
    onDiscoverHosts: suspend (Int) -> List<DiscoveredHost>,
    onSaveAndConnect: (ConnectionConfig) -> Unit,
    onMove: (Float, Float) -> Unit,
    onScroll: (Float, Float) -> Unit,
    onClick: (String, String) -> Unit,
    onSendKeys: (List<String>) -> Unit,
    onSendText: (String, Boolean) -> Unit,
    onRequestEditText: (String) -> Unit,
    onDismissEditText: () -> Unit,
    onStartRecording: () -> Unit,
    onStopRecording: () -> Unit,
    onStopRecordingForEdit: () -> Unit,
    onCancelRecording: () -> Unit,
    onTapFeedback: () -> Unit,
) {
    var directInput by remember { mutableStateOf("") }
    var showDirectInput by remember { mutableStateOf(false) }
    var showHistoryDialog by remember { mutableStateOf(false) }
    var gestureZone by remember { mutableStateOf(VoiceGestureZone.SEND) }

    val startRecState by rememberUpdatedState(onStartRecording)
    val stopRecState by rememberUpdatedState(onStopRecording)
    val stopEditState by rememberUpdatedState(onStopRecordingForEdit)
    val cancelRecState by rememberUpdatedState(onCancelRecording)
    val tapFeedbackState by rememberUpdatedState(onTapFeedback)
    val toggleStealthState by rememberUpdatedState(onToggleStealth)

    val dotColor = when (status.connectionState) {
        ConnectionState.CONNECTED -> AccentGreen
        ConnectionState.CONNECTING -> AccentAmber
        ConnectionState.DISCONNECTED -> AccentRed
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(BgDark)
                .statusBarsPadding()
                .navigationBarsPadding()
                .imePadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // 1. Top status & quick switches
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(SurfaceDark)
                    .border(1.dp, BorderSubtle, RoundedCornerShape(14.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(dotColor),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clickable { onOpenConfig() },
                ) {
                    Text(
                        text = status.statusMessage,
                        color = TextPrimary,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = if (config.volumeKeyBlindMode) {
                            "盲操: 音量-按住说 · 音量+${config.volumeUpAction.label.substringBefore(" ")}"
                        } else {
                            "音量键盲操已关闭"
                        },
                        color = TextSecondary,
                        fontSize = 11.sp,
                        maxLines = 1,
                    )
                }
                IconButton(onClick = onOpenConfig, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Default.Settings, contentDescription = "设置", tint = TextPrimary)
                }
            }

            // 2. Toggle pills bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ToggleChip(
                    label = "自动回车",
                    active = config.autoEnter,
                    activeColor = AccentBlue,
                    onClick = onToggleAutoEnter,
                )
                ToggleChip(
                    label = if (status.llmPolishAvailable) "AI润色" else "AI润色(未配)",
                    active = config.llmPolish && status.llmPolishAvailable,
                    activeColor = Color(0xFF8B5CF6),
                    onClick = onToggleLlmPolish,
                )
                ToggleChip(
                    label = "黑屏盲操",
                    active = stealthMode,
                    activeColor = AccentAmber,
                    onClick = onToggleStealth,
                )
                ToggleChip(
                    label = "打字框",
                    active = showDirectInput,
                    activeColor = AccentGreen,
                    onClick = { showDirectInput = !showDirectInput },
                )
            }

            // 3. Recent transcript preview + 1-tap Undo + History (last 10)
            if (status.lastTranscript.isNotBlank() || status.history.isNotEmpty()) {
                Surface(
                    color = SurfaceElevated.copy(alpha = 0.75f),
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            text = status.lastTranscript.ifBlank { status.history.firstOrNull().orEmpty() },
                            color = TextSecondary,
                            fontSize = 12.sp,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier
                                .weight(1f)
                                .clickable {
                                    val txt = status.lastTranscript.ifBlank { status.history.firstOrNull().orEmpty() }
                                    if (txt.isNotBlank()) onRequestEditText(txt)
                                },
                        )
                        MiniActionPill("撤回", AccentRed) {
                            onSendKeys(listOf("ctrl", "z"))
                            onTapFeedback()
                        }
                        if (status.history.isNotEmpty()) {
                            MiniActionPill("历史(${status.history.size})", AccentBlue) {
                                showHistoryDialog = true
                            }
                        }
                    }
                }
            }

            // 4. Large touchpad area
            TouchpadSurface(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                sensitivity = config.sensitivity,
                naturalScroll = config.naturalScroll,
                enabled = !stealthMode,
                isRecording = isRecording,
                onMove = onMove,
                onScroll = onScroll,
                onClick = onClick,
                onTapFeedback = onTapFeedback,
            )

            // 5. Optional direct text input (phone IME voice typing fallback)
            if (showDirectInput) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    OutlinedTextField(
                        value = directInput,
                        onValueChange = { directInput = it },
                        placeholder = { Text("可用手机输入法打字/语音后直发电脑", fontSize = 13.sp) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = AccentBlue,
                            unfocusedBorderColor = BorderSubtle,
                        ),
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(
                        onClick = {
                            if (directInput.isNotBlank()) {
                                onSendText(directInput, config.autoEnter)
                                directInput = ""
                            }
                        },
                        modifier = Modifier
                            .size(48.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(AccentBlue),
                    ) {
                        Icon(Icons.Default.Send, contentDescription = "发送", tint = Color.White)
                    }
                }
            }

            // 6. Left / Right mouse buttons + Vibe Coding Macro Deck
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                MacroKeyButton("左键", Modifier.weight(1.2f)) { onClick("left", "click"); onTapFeedback() }
                MacroKeyButton("右键", Modifier.weight(1.2f)) { onClick("right", "click"); onTapFeedback() }
                MacroKeyButton("Enter", Modifier.weight(1.1f), highlight = true) { onSendKeys(listOf("enter")); onTapFeedback() }
                MacroKeyButton("撤销", Modifier.weight(1f)) { onSendKeys(listOf("ctrl", "z")); onTapFeedback() }
                MacroKeyButton("Esc", Modifier.weight(0.9f)) { onSendKeys(listOf("esc")); onTapFeedback() }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                MacroKeyButton("Tab", Modifier.weight(1f)) { onSendKeys(listOf("tab")); onTapFeedback() }
                MacroKeyButton("退格", Modifier.weight(1f)) { onSendKeys(listOf("backspace")); onTapFeedback() }
                MacroKeyButton("Win+Tab", Modifier.weight(1.25f), highlight = true) { onSendKeys(listOf("win", "tab")); onTapFeedback() }
                MacroKeyButton("Alt+Tab", Modifier.weight(1.15f)) { onSendKeys(listOf("alt", "tab")); onTapFeedback() }
                MacroKeyButton("Ctrl+↵", Modifier.weight(1.1f)) { onSendKeys(listOf("ctrl", "enter")); onTapFeedback() }
            }

            // 7. Big thumb Push-to-Talk button (also mirrors Volume-Down blind trigger)
            val pttBg = when {
                isRecording -> AccentRed
                status.voiceState == "transcribing" -> AccentAmber
                status.connectionState == ConnectionState.CONNECTED -> AccentBlue
                else -> SurfaceElevated
            }
            val pttText = when {
                isRecording -> "松开发送 · 左上取消 · 右上编辑"
                status.voiceState == "transcribing" -> "正在识别..."
                status.connectionState == ConnectionState.CONNECTED -> "按住说话  (左上取消 · 右上编辑)"
                else -> "未连接电脑 · 点右上角扫码配对"
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(60.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(pttBg)
                    .pointerInput(Unit) {
                        awaitEachGesture {
                            val down = awaitFirstDown(requireUnconsumed = false)
                            val startPos = down.position
                            var currentZone = VoiceGestureZone.SEND
                            gestureZone = currentZone
                            startRecState()

                            try {
                                while (true) {
                                    val event = awaitPointerEvent()
                                    val change = event.changes.firstOrNull { it.id == down.id } ?: break
                                    if (!change.pressed) {
                                        break
                                    }
                                    val dx = change.position.x - startPos.x
                                    val dy = change.position.y - startPos.y
                                    val nextZone = when {
                                        dy < -80f && dx < -30f -> VoiceGestureZone.CANCEL
                                        dy < -80f && dx > 30f -> VoiceGestureZone.EDIT
                                        else -> VoiceGestureZone.SEND
                                    }
                                    if (nextZone != currentZone) {
                                        currentZone = nextZone
                                        gestureZone = nextZone
                                        tapFeedbackState()
                                    }
                                    change.consume()
                                }
                            } finally {
                                when (currentZone) {
                                    VoiceGestureZone.CANCEL -> cancelRecState()
                                    VoiceGestureZone.EDIT -> stopEditState()
                                    VoiceGestureZone.SEND -> stopRecState()
                                }
                                gestureZone = VoiceGestureZone.SEND
                            }
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = pttText,
                    color = if (status.voiceState == "transcribing") Color(0xFF111827) else Color.White,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
        }

        // WeChat-style live transcript + up-left Cancel / up-right Edit overlay
        if ((isRecording || waitingEditTranscript) && !stealthMode) {
            VoiceRecordingOverlay(
                zone = gestureZone,
                partialText = status.partialTranscript,
                isTranscribingForEdit = waitingEditTranscript && !isRecording,
            )
        }

        // Full-black OLED pseudo-sleep overlay: blocks accidental touches while keeping volume keys live
        if (stealthMode) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black)
                    .pointerInput(Unit) {
                        detectTapGestures(
                            onDoubleTap = { toggleStealthState() },
                        )
                    }
                    .statusBarsPadding()
                    .padding(24.dp),
                contentAlignment = Alignment.TopCenter,
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(
                        text = if (isRecording) "● 正在盲操录音（松开音量-发送）" else "黑屏盲操已开启 · 按住「音量-」说话\n双击屏幕任意位置退出",
                        color = if (isRecording) AccentRed.copy(alpha = 0.85f) else Color(0xFF3A3A3A),
                        fontSize = 12.sp,
                        textAlign = TextAlign.Center,
                        lineHeight = 18.sp,
                    )
                }
            }
        }
    }

    if (showConnectDialog) {
        ConnectDialog(
            initialConfig = config,
            onDiscoverHosts = onDiscoverHosts,
            onDismiss = onDismissConnectDialog,
            onApplyAndConnect = onSaveAndConnect,
        )
    }

    if (showHistoryDialog) {
        AlertDialog(
            onDismissRequest = { showHistoryDialog = false },
            containerColor = SurfaceDark,
            title = {
                Text("最近语音历史（点击重新发送到电脑）", fontSize = 16.sp, fontWeight = FontWeight.Bold)
            },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    status.history.forEachIndexed { idx, item ->
                        Surface(
                            color = SurfaceElevated,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    onSendText(item, config.autoEnter)
                                    showHistoryDialog = false
                                },
                        ) {
                            Text(
                                text = "${idx + 1}. $item",
                                color = TextPrimary,
                                fontSize = 13.sp,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            )
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showHistoryDialog = false }) {
                    Text("关闭")
                }
            },
        )
    }

    if (pendingEditText != null) {
        EditTranscriptDialog(
            initialText = pendingEditText,
            initialAutoEnter = config.autoEnter,
            onDismiss = onDismissEditText,
            onSend = { edited, autoEnter ->
                onSendText(edited, autoEnter)
                onDismissEditText()
            },
        )
    }
}

@Composable
private fun MiniActionPill(
    label: String,
    accent: Color,
    onClick: () -> Unit,
) {
    Surface(
        color = accent.copy(alpha = 0.18f),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier
            .border(1.dp, accent.copy(alpha = 0.6f), RoundedCornerShape(8.dp))
            .clickable { onClick() },
    ) {
        Text(
            text = label,
            color = accent,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun ToggleChip(
    label: String,
    active: Boolean,
    activeColor: Color,
    onClick: () -> Unit,
) {
    Surface(
        color = if (active) activeColor.copy(alpha = 0.22f) else SurfaceDark,
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier
            .border(
                width = 1.dp,
                color = if (active) activeColor else BorderSubtle,
                shape = RoundedCornerShape(10.dp),
            )
            .clickable { onClick() },
    ) {
        Text(
            text = label,
            color = if (active) activeColor else TextSecondary,
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
        )
    }
}

@Composable
private fun MacroKeyButton(
    label: String,
    modifier: Modifier = Modifier,
    highlight: Boolean = false,
    onClick: () -> Unit,
) {
    Surface(
        color = if (highlight) SurfaceElevated else SurfaceDark,
        shape = RoundedCornerShape(10.dp),
        modifier = modifier
            .height(40.dp)
            .border(
                1.dp,
                if (highlight) AccentBlue.copy(alpha = 0.7f) else BorderSubtle,
                RoundedCornerShape(10.dp),
            )
            .clickable { onClick() },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = label,
                color = if (highlight) AccentBlue else TextPrimary,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

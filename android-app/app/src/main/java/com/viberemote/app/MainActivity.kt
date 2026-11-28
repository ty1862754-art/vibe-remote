package com.viberemote.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.viberemote.app.audio.AudioRecorder
import com.viberemote.app.haptic.HapticHelper
import com.viberemote.app.model.ConfigStore
import com.viberemote.app.model.ConnectionConfig
import com.viberemote.app.network.ConnectionState
import com.viberemote.app.network.RemoteClient
import com.viberemote.app.ui.MainScreen
import com.viberemote.app.ui.VibeRemoteTheme

class MainActivity : ComponentActivity() {
    private lateinit var configStore: ConfigStore
    private lateinit var haptic: HapticHelper
    private lateinit var client: RemoteClient
    private lateinit var audioRecorder: AudioRecorder

    private val configState = mutableStateOf(ConnectionConfig())
    private val isRecordingState = mutableStateOf(false)
    private val waitingEditState = mutableStateOf(false)
    private val pendingEditTextState = mutableStateOf<String?>(null)
    private val stealthModeState = mutableStateOf(false)
    private val showConnectDialogState = mutableStateOf(false)

    private val micPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(this, "需要麦克风权限才能语音输入", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        configStore = ConfigStore(this)
        haptic = HapticHelper(this)
        audioRecorder = AudioRecorder(lifecycleScope)
        client = RemoteClient(
            scope = lifecycleScope,
            onTranscriptPasted = {
                waitingEditState.value = false
                haptic.successDoublePulse()
            },
            onEditTranscript = { text ->
                runOnUiThread {
                    waitingEditState.value = false
                    pendingEditTextState.value = text
                    haptic.tick()
                }
            },
            onVoiceIdle = {
                waitingEditState.value = false
            },
            onServerError = { msg ->
                waitingEditState.value = false
                haptic.errorBuzz()
                runOnUiThread {
                    Toast.makeText(this, msg.ifBlank { "识别出错" }, Toast.LENGTH_SHORT).show()
                }
            },
        )

        val saved = configStore.load()
        configState.value = saved
        if (saved.isValid) {
            client.connect(saved)
        } else {
            showConnectDialogState.value = true
        }

        setContent {
            VibeRemoteTheme {
                val cfg by configState
                val serverStatus by client.status.collectAsState()
                val isRec by isRecordingState
                val waitingEdit by waitingEditState
                val pendingEdit by pendingEditTextState
                val stealth by stealthModeState
                val showDlg by showConnectDialogState

                MainScreen(
                    config = cfg,
                    status = serverStatus,
                    isRecording = isRec,
                    waitingEditTranscript = waitingEdit,
                    pendingEditText = pendingEdit,
                    stealthMode = stealth,
                    onToggleStealth = {
                        stealthModeState.value = !stealthModeState.value
                        applyBrightness(stealthModeState.value)
                        haptic.tick()
                    },
                    onToggleAutoEnter = {
                        val next = cfg.copy(autoEnter = !cfg.autoEnter)
                        configState.value = next
                        configStore.save(next)
                        haptic.tick()
                    },
                    onToggleLlmPolish = {
                        val next = cfg.copy(llmPolish = !cfg.llmPolish)
                        configState.value = next
                        configStore.save(next)
                        haptic.tick()
                    },
                    onOpenConfig = { showConnectDialogState.value = true },
                    showConnectDialog = showDlg,
                    onDismissConnectDialog = { showConnectDialogState.value = false },
                    onDiscoverHosts = { port -> client.discoverLanServers(port) },
                    onSaveAndConnect = { updated ->
                        configState.value = updated
                        configStore.save(updated)
                        showConnectDialogState.value = false
                        client.connect(updated)
                    },
                    onMove = { dx, dy -> client.sendMouseMove(dx, dy) },
                    onScroll = { dx, dy -> client.sendScroll(dx, dy) },
                    onClick = { btn, act -> client.sendClick(btn, act) },
                    onSendKeys = { keys -> client.sendKeys(keys) },
                    onSendText = { text, autoEnter ->
                        client.sendText(text, autoEnter)
                        haptic.tick()
                    },
                    onRequestEditText = { text -> pendingEditTextState.value = text },
                    onDismissEditText = { pendingEditTextState.value = null },
                    onStartRecording = { startVoiceCapture() },
                    onStopRecording = { stopVoiceCapture(editMode = false) },
                    onStopRecordingForEdit = { stopVoiceCapture(editMode = true) },
                    onCancelRecording = { cancelVoiceCapture() },
                    onTapFeedback = { haptic.tick() },
                )
            }
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val cfg = configState.value
        if (!cfg.volumeKeyBlindMode) {
            return super.onKeyDown(keyCode, event)
        }
        return when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                if (event?.repeatCount == 0) {
                    startVoiceCapture()
                }
                true
            }

            KeyEvent.KEYCODE_VOLUME_UP -> {
                if (event?.repeatCount == 0) {
                    client.sendKeys(cfg.volumeUpAction.keys)
                    haptic.tick()
                }
                true
            }

            else -> super.onKeyDown(keyCode, event)
        }
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        val cfg = configState.value
        if (!cfg.volumeKeyBlindMode) {
            return super.onKeyUp(keyCode, event)
        }
        return when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                stopVoiceCapture()
                true
            }

            KeyEvent.KEYCODE_VOLUME_UP -> true
            else -> super.onKeyUp(keyCode, event)
        }
    }

    private fun startVoiceCapture() {
        if (isRecordingState.value) return

        if (client.status.value.connectionState != ConnectionState.CONNECTED) {
            haptic.errorBuzz()
            showConnectDialogState.value = true
            return
        }

        val hasMic = ContextCompat.checkSelfPermission(
            this, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasMic) {
            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }

        val cfg = configState.value
        client.sendAudioStart(
            sampleRate = 16000,
            autoEnter = cfg.autoEnter,
            polish = cfg.llmPolish,
        )
        val started = audioRecorder.start(
            onChunk = { chunk -> client.sendAudioChunk(chunk) },
            onError = { err ->
                runOnUiThread {
                    isRecordingState.value = false
                    haptic.errorBuzz()
                    Toast.makeText(this, err, Toast.LENGTH_SHORT).show()
                }
                client.sendAudioCancel()
            },
        )
        if (started) {
            isRecordingState.value = true
            haptic.recordStart()
        }
    }

    private fun stopVoiceCapture(editMode: Boolean = false) {
        if (!isRecordingState.value) return
        isRecordingState.value = false
        audioRecorder.stop()
        if (editMode) {
            waitingEditState.value = true
            client.sendAudioEnd("edit")
        } else {
            client.sendAudioEnd("send")
        }
        haptic.recordStop()
    }

    private fun cancelVoiceCapture() {
        if (!isRecordingState.value) return
        isRecordingState.value = false
        waitingEditState.value = false
        audioRecorder.stop()
        client.sendAudioCancel()
        haptic.tick()
    }

    private fun applyBrightness(dim: Boolean) {
        val lp = window.attributes
        lp.screenBrightness = if (dim) 0.01f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        window.attributes = lp
    }

    override fun onResume() {
        super.onResume()
        client.ensureAlive()
    }

    override fun onPause() {
        super.onPause()
        if (isRecordingState.value) {
            stopVoiceCapture()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        audioRecorder.stop()
        client.disconnect()
    }
}

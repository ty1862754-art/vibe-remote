package com.viberemote.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class AudioRecorder(
    private val scope: CoroutineScope,
    private val sampleRate: Int = 16000,
) {
    private var recorder: AudioRecord? = null
    private var readJob: Job? = null

    @Volatile
    var isRecording: Boolean = false
        private set

    @SuppressLint("MissingPermission")
    fun start(onChunk: (ByteArray) -> Unit, onError: (String) -> Unit): Boolean {
        if (isRecording) return true

        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val minBufSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        if (minBufSize <= 0) {
            onError("当前设备不支持 16kHz PCM 录音")
            return false
        }

        val bufferSize = maxOf(minBufSize * 2, 6400)
        val audioRecord = createRecorder(channelConfig, audioFormat, bufferSize)
        if (audioRecord == null || audioRecord.state != AudioRecord.STATE_INITIALIZED) {
            audioRecord?.release()
            onError("麦克风初始化失败，请检查录音权限")
            return false
        }

        recorder = audioRecord
        isRecording = true
        runCatching { audioRecord.startRecording() }.onFailure {
            stop()
            onError("启动录音失败: ${it.message}")
            return false
        }

        // Stream ~100ms chunks (16000 Hz * 2 bytes * 0.1s = 3200 bytes)
        readJob = scope.launch(Dispatchers.IO) {
            val chunkBuf = ByteArray(3200)
            while (isActive && isRecording) {
                val readBytes = audioRecord.read(chunkBuf, 0, chunkBuf.size)
                if (readBytes > 0) {
                    onChunk(chunkBuf.copyOf(readBytes))
                } else if (readBytes < 0) {
                    break
                }
            }
        }
        return true
    }

    @SuppressLint("MissingPermission")
    private fun createRecorder(channelConfig: Int, audioFormat: Int, bufferSize: Int): AudioRecord? {
        val sources = listOf(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            MediaRecorder.AudioSource.MIC,
        )
        for (src in sources) {
            val candidate = runCatching {
                AudioRecord(src, sampleRate, channelConfig, audioFormat, bufferSize)
            }.getOrNull()
            if (candidate != null && candidate.state == AudioRecord.STATE_INITIALIZED) {
                return candidate
            }
            candidate?.release()
        }
        return null
    }

    fun stop() {
        isRecording = false
        readJob?.cancel()
        readJob = null
        recorder?.let { rec ->
            runCatching { rec.stop() }
            runCatching { rec.release() }
        }
        recorder = null
    }
}

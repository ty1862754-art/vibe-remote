package com.viberemote.app.haptic

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

class HapticHelper(context: Context) {
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        val mgr = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
        mgr?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    fun tick() {
        vibrateOneShot(20L, 90)
    }

    fun recordStart() {
        vibrateOneShot(45L, 180)
    }

    fun recordStop() {
        vibrateOneShot(30L, 140)
    }

    fun successDoublePulse() {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        val timings = longArrayOf(0, 35, 60, 45)
        val amplitudes = intArrayOf(0, 150, 0, 220)
        runCatching {
            v.vibrate(VibrationEffect.createWaveform(timings, amplitudes, -1))
        }
    }

    fun errorBuzz() {
        vibrateOneShot(140L, 230)
    }

    private fun vibrateOneShot(durationMs: Long, amplitude: Int) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        runCatching {
            v.vibrate(VibrationEffect.createOneShot(durationMs, amplitude))
        }
    }
}

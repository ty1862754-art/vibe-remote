package com.viberemote.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.hypot
import kotlin.math.pow

@Composable
fun TouchpadSurface(
    modifier: Modifier = Modifier,
    sensitivity: Float,
    naturalScroll: Boolean,
    enabled: Boolean,
    isRecording: Boolean,
    onMove: (Float, Float) -> Unit,
    onScroll: (Float, Float) -> Unit,
    onClick: (button: String, action: String) -> Unit,
    onTapFeedback: () -> Unit,
) {
    val currentSensitivity by rememberUpdatedState(sensitivity)
    val currentNaturalScroll by rememberUpdatedState(naturalScroll)
    val currentEnabled by rememberUpdatedState(enabled)
    val currentOnMove by rememberUpdatedState(onMove)
    val currentOnScroll by rememberUpdatedState(onScroll)
    val currentOnClick by rememberUpdatedState(onClick)
    val currentOnTapFeedback by rememberUpdatedState(onTapFeedback)

    val borderColor = when {
        isRecording -> AccentRed
        !enabled -> BorderSubtle.copy(alpha = 0.4f)
        else -> BorderSubtle
    }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(if (enabled) SurfaceDark else BgDark)
            .border(1.5.dp, borderColor, RoundedCornerShape(18.dp))
            .pointerInput(Unit) {
                var lastTapUpTime = 0L

                awaitEachGesture {
                    val firstEvent = awaitPointerEvent()
                    if (!currentEnabled) return@awaitEachGesture
                    if (firstEvent.type != PointerEventType.Press) return@awaitEachGesture

                    val downTime = System.currentTimeMillis()
                    var maxPointers = firstEvent.changes.count { it.pressed }
                    var totalDistance = 0f
                    var isDragging = false

                    // Double-tap-and-hold initiates left mouse drag
                    if (maxPointers == 1 && (downTime - lastTapUpTime) < 230L) {
                        isDragging = true
                        currentOnClick("left", "down")
                        currentOnTapFeedback()
                    }

                    val lastPositions = mutableMapOf<Long, Offset>()
                    firstEvent.changes.forEach { ch ->
                        lastPositions[ch.id.value] = ch.position
                    }

                    while (true) {
                        val event = awaitPointerEvent()
                        val pressedChanges = event.changes.filter { it.pressed }
                        val pressedCount = pressedChanges.size
                        if (pressedCount > maxPointers) {
                            maxPointers = pressedCount
                        }

                        if (pressedCount == 1 && maxPointers == 1) {
                            val ch = pressedChanges[0]
                            val prev = lastPositions[ch.id.value] ?: ch.position
                            val delta = ch.position - prev
                            lastPositions[ch.id.value] = ch.position
                            val dist = hypot(delta.x, delta.y)
                            if (dist > 0.1f) {
                                totalDistance += dist
                                // Gentle pointer acceleration: slow = pixel precise, fast = wide travel
                                val accel = 1f + (dist / 18f).coerceAtMost(2.2f).pow(1.15f) * 0.55f
                                val scale = currentSensitivity * accel
                                currentOnMove(delta.x * scale, delta.y * scale)
                                ch.consume()
                            }
                        } else if (pressedCount == 2) {
                            var sumDx = 0f
                            var sumDy = 0f
                            var counted = 0
                            for (ch in pressedChanges) {
                                val prev = lastPositions[ch.id.value]
                                lastPositions[ch.id.value] = ch.position
                                if (prev != null) {
                                    sumDx += ch.position.x - prev.x
                                    sumDy += ch.position.y - prev.y
                                    counted++
                                }
                                ch.consume()
                            }
                            if (counted > 0) {
                                val avgDx = sumDx / counted
                                val avgDy = sumDy / counted
                                totalDistance += hypot(avgDx, avgDy)
                                // Windows wheel: positive = scroll up, negative = scroll down
                                val scrollSign = if (currentNaturalScroll) 1f else -1f
                                currentOnScroll(avgDx * 3.5f * scrollSign, avgDy * 4.5f * scrollSign)
                            }
                        } else {
                            pressedChanges.forEach { ch ->
                                lastPositions[ch.id.value] = ch.position
                            }
                        }

                        if (pressedCount == 0) {
                            break
                        }
                    }

                    val upTime = System.currentTimeMillis()
                    val duration = upTime - downTime

                    if (isDragging) {
                        currentOnClick("left", "up")
                        lastTapUpTime = 0L
                    } else if (duration < 230L && totalDistance < 22f) {
                        when (maxPointers) {
                            1 -> {
                                currentOnClick("left", "click")
                                currentOnTapFeedback()
                                lastTapUpTime = upTime
                            }

                            2 -> {
                                currentOnClick("right", "click")
                                currentOnTapFeedback()
                                lastTapUpTime = 0L
                            }

                            3 -> {
                                currentOnClick("middle", "click")
                                currentOnTapFeedback()
                                lastTapUpTime = 0L
                            }
                        }
                    } else {
                        lastTapUpTime = 0L
                    }
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(20.dp),
        ) {
            if (!enabled) {
                Text(
                    text = "防误触盲操模式已开启\n按住「音量-」直接说话，点上方解锁触控板",
                    color = TextSecondary.copy(alpha = 0.7f),
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                )
            } else if (isRecording) {
                Text(
                    text = "正在录音...\n松开按键立即识别并粘贴到电脑",
                    color = AccentRed,
                    fontSize = 16.sp,
                    textAlign = TextAlign.Center,
                )
            } else {
                Text(
                    text = "单指滑动移光标 · 轻点左键 · 双击按住拖拽\n双指滑动滚轮 · 双指轻点右键",
                    color = TextSecondary.copy(alpha = 0.55f),
                    fontSize = 12.sp,
                    textAlign = TextAlign.Center,
                    lineHeight = 20.sp,
                )
            }
        }
    }
}

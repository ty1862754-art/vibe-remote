package com.viberemote.app.ui

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

enum class VoiceGestureZone {
    SEND,
    CANCEL,
    EDIT,
}

@Composable
fun VoiceRecordingOverlay(
    zone: VoiceGestureZone,
    partialText: String,
    isTranscribingForEdit: Boolean,
) {
    val pulseTransition = rememberInfiniteTransition(label = "orb_pulse")
    val pulseScale by pulseTransition.animateFloat(
        initialValue = 0.92f,
        targetValue = 1.18f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 750),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse_scale",
    )

    val cancelScale by animateFloatAsState(
        targetValue = if (zone == VoiceGestureZone.CANCEL) 1.09f else 1.0f,
        label = "cancel_scale",
    )
    val editScale by animateFloatAsState(
        targetValue = if (zone == VoiceGestureZone.EDIT) 1.09f else 1.0f,
        label = "edit_scale",
    )

    val orbColor = when {
        isTranscribingForEdit -> AccentBlue
        zone == VoiceGestureZone.CANCEL -> AccentRed
        zone == VoiceGestureZone.EDIT -> Color(0xFF22C55E)
        else -> Color(0xFF2EC866)
    }

    val topHint = when {
        isTranscribingForEdit -> "正在完成识别，即将打开编辑框..."
        zone == VoiceGestureZone.CANCEL -> "松开手指，取消发送"
        zone == VoiceGestureZone.EDIT -> "松开手指，编辑识别文字后再发送"
        else -> "松开直接发送到电脑 · 左上取消 · 右上编辑"
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xE6080A0E)),
    ) {
        // Center: Live recognized text card + glowing green orb (WeChat style)
        Column(
            modifier = Modifier
                .align(Alignment.Center)
                .padding(horizontal = 24.dp)
                .padding(bottom = 120.dp)
                .statusBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(22.dp),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 84.dp, max = 210.dp)
                    .clip(RoundedCornerShape(20.dp))
                    .background(
                        when (zone) {
                            VoiceGestureZone.CANCEL -> AccentRed.copy(alpha = 0.16f)
                            VoiceGestureZone.EDIT -> Color(0xFF10B981).copy(alpha = 0.18f)
                            VoiceGestureZone.SEND -> Color(0xFF1A222E).copy(alpha = 0.92f)
                        }
                    )
                    .border(
                        width = 1.dp,
                        color = orbColor.copy(alpha = 0.55f),
                        shape = RoundedCornerShape(20.dp),
                    )
                    .padding(horizontal = 18.dp, vertical = 14.dp),
                contentAlignment = Alignment.Center,
            ) {
                val displayText = when {
                    partialText.isNotBlank() -> partialText
                    isTranscribingForEdit -> "正在识别最终文字..."
                    else -> "正在聆听，请直接说话..."
                }
                Text(
                    text = displayText,
                    color = if (partialText.isNotBlank()) Color.White else TextSecondary,
                    fontSize = if (partialText.isNotBlank()) 18.sp else 15.sp,
                    fontWeight = if (partialText.isNotBlank()) FontWeight.Medium else FontWeight.Normal,
                    lineHeight = 26.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                )
            }

            // Glowing pulsing orb (matching the screenshot centerpiece)
            Box(
                modifier = Modifier.size(92.dp),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(86.dp)
                        .graphicsLayer {
                            scaleX = pulseScale
                            scaleY = pulseScale
                        }
                        .clip(CircleShape)
                        .background(
                            Brush.radialGradient(
                                colors = listOf(
                                    orbColor.copy(alpha = 0.45f),
                                    orbColor.copy(alpha = 0.0f),
                                )
                            )
                        ),
                )
                Box(
                    modifier = Modifier
                        .size(54.dp)
                        .clip(CircleShape)
                        .background(orbColor),
                )
            }

            Text(
                text = topHint,
                color = when (zone) {
                    VoiceGestureZone.CANCEL -> AccentRed
                    VoiceGestureZone.EDIT -> Color(0xFF34D399)
                    VoiceGestureZone.SEND -> TextSecondary
                },
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
            )
        }

        // Bottom WeChat-style angled Cancel / Edit pills + curved send dome
        Box(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(230.dp),
        ) {
            if (!isTranscribingForEdit) {
                Row(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .padding(horizontal = 14.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(22.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Up-Left: Cancel
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .height(62.dp)
                            .graphicsLayer {
                                rotationZ = -11f
                                scaleX = cancelScale
                                scaleY = cancelScale
                            }
                            .clip(RoundedCornerShape(32.dp))
                            .background(
                                if (zone == VoiceGestureZone.CANCEL) AccentRed else Color(0xFF23252B)
                            )
                            .border(
                                width = if (zone == VoiceGestureZone.CANCEL) 1.5.dp else 1.dp,
                                color = if (zone == VoiceGestureZone.CANCEL) Color.White.copy(alpha = 0.45f) else Color(0xFF353944),
                                shape = RoundedCornerShape(32.dp),
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = "取消",
                            color = Color.White,
                            fontSize = 17.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }

                    // Up-Right: Edit
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .height(62.dp)
                            .graphicsLayer {
                                rotationZ = 11f
                                scaleX = editScale
                                scaleY = editScale
                            }
                            .clip(RoundedCornerShape(32.dp))
                            .background(
                                if (zone == VoiceGestureZone.EDIT) Color(0xFF16A34A) else Color(0xFF23252B)
                            )
                            .border(
                                width = if (zone == VoiceGestureZone.EDIT) 1.5.dp else 1.dp,
                                color = if (zone == VoiceGestureZone.EDIT) Color.White.copy(alpha = 0.45f) else Color(0xFF353944),
                                shape = RoundedCornerShape(32.dp),
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = "编辑",
                            color = Color.White,
                            fontSize = 17.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }

            // Bottom curved dome (matching the grey-white arc in screenshot)
            val arcColor = when {
                isTranscribingForEdit -> Color(0xFF2B3449)
                zone == VoiceGestureZone.SEND -> Color(0xFF7B808A)
                else -> Color(0xFF2A2D35)
            }
            Canvas(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .height(132.dp),
            ) {
                val w = size.width
                val h = size.height
                drawOval(
                    color = arcColor,
                    topLeft = Offset(-w * 0.22f, 0f),
                    size = Size(w * 1.44f, h * 2.2f),
                )
            }

            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .navigationBarsPadding()
                    .padding(bottom = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = when {
                        isTranscribingForEdit -> "识别中..."
                        zone == VoiceGestureZone.CANCEL -> "松开取消"
                        zone == VoiceGestureZone.EDIT -> "松开编辑"
                        else -> "松开发送"
                    },
                    color = if (zone == VoiceGestureZone.SEND && !isTranscribingForEdit) {
                        Color(0xFF111827)
                    } else {
                        Color.White.copy(alpha = 0.85f)
                    },
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
fun EditTranscriptDialog(
    initialText: String,
    initialAutoEnter: Boolean,
    onDismiss: () -> Unit,
    onSend: (text: String, autoEnter: Boolean) -> Unit,
) {
    var editedText by remember(initialText) { mutableStateOf(initialText) }
    var autoEnter by remember(initialAutoEnter) { mutableStateOf(initialAutoEnter) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceDark,
        title = {
            Text("编辑语音识别内容", fontSize = 17.sp, fontWeight = FontWeight.Bold)
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = editedText,
                    onValueChange = { editedText = it },
                    minLines = 3,
                    maxLines = 7,
                    placeholder = { Text("修改识别文字后发送到电脑光标处") },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = AccentGreen,
                        unfocusedBorderColor = BorderSubtle,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("发送后自动按回车", fontSize = 13.sp, color = TextSecondary)
                    Switch(checked = autoEnter, onCheckedChange = { autoEnter = it })
                }
                Spacer(modifier = Modifier.height(2.dp))
            }
        },
        confirmButton = {
            Button(
                enabled = editedText.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF16A34A)),
                onClick = { onSend(editedText.trim(), autoEnter) },
            ) {
                Text("发送到电脑", color = Color.White)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    )
}

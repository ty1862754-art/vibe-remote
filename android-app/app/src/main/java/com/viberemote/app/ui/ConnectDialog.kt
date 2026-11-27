package com.viberemote.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.viberemote.app.model.ConnectionConfig
import com.viberemote.app.model.DiscoveredHost
import com.viberemote.app.model.VolumeUpAction
import kotlinx.coroutines.launch
import java.util.Locale

@Composable
fun ConnectDialog(
    initialConfig: ConnectionConfig,
    onDiscoverHosts: suspend (Int) -> List<DiscoveredHost>,
    onDismiss: () -> Unit,
    onApplyAndConnect: (ConnectionConfig) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var host by remember { mutableStateOf(initialConfig.host) }
    var wsPort by remember { mutableStateOf(initialConfig.wsPort.toString()) }
    var udpPort by remember { mutableStateOf(initialConfig.udpPort.toString()) }
    var token by remember { mutableStateOf(initialConfig.token) }
    var sensitivity by remember { mutableFloatStateOf(initialConfig.sensitivity) }
    var naturalScroll by remember { mutableStateOf(initialConfig.naturalScroll) }
    var volumeBlind by remember { mutableStateOf(initialConfig.volumeKeyBlindMode) }
    var volumeUpAction by remember { mutableStateOf(initialConfig.volumeUpAction) }

    var discovered by remember { mutableStateOf<List<DiscoveredHost>>(emptyList()) }
    var discovering by remember { mutableStateOf(false) }
    var scanError by remember { mutableStateOf<String?>(null) }

    val qrLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
        val raw = result.contents ?: return@rememberLauncherForActivityResult
        val parsed = ConnectionConfig.fromQrUri(raw)
        if (parsed != null) {
            val merged = initialConfig.copy(
                host = parsed.host,
                wsPort = parsed.wsPort,
                udpPort = parsed.udpPort,
                token = parsed.token,
                sensitivity = sensitivity,
                naturalScroll = naturalScroll,
                volumeKeyBlindMode = volumeBlind,
                volumeUpAction = volumeUpAction,
            )
            onApplyAndConnect(merged)
        } else {
            scanError = "未识别为 VibeRemote 配对二维码"
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SurfaceDark,
        title = {
            Text("连接电脑与盲操设置", fontWeight = FontWeight.Bold, fontSize = 18.sp)
        },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Button(
                        modifier = Modifier.weight(1f),
                        onClick = {
                            scanError = null
                            val opts = ScanOptions()
                                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                                .setPrompt("扫描电脑端终端或 /pair 页面二维码")
                                .setBeepEnabled(false)
                                .setOrientationLocked(false)
                            qrLauncher.launch(opts)
                        },
                    ) {
                        Text("扫码一键配对")
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !discovering,
                        onClick = {
                            discovering = true
                            scope.launch {
                                val uPort = udpPort.toIntOrNull() ?: 8766
                                discovered = onDiscoverHosts(uPort)
                                discovering = false
                            }
                        },
                    ) {
                        Text(if (discovering) "搜索中..." else "搜索局域网")
                    }
                }

                if (scanError != null) {
                    Text(scanError.orEmpty(), color = AccentRed, fontSize = 12.sp)
                }

                if (discovered.isNotEmpty()) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("发现以下局域网电脑（点击填入）：", color = TextSecondary, fontSize = 12.sp)
                        discovered.forEach { item ->
                            Surface(
                                color = SurfaceElevated,
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        host = item.host
                                        wsPort = item.wsPort.toString()
                                        udpPort = item.udpPort.toString()
                                    },
                            ) {
                                Text(
                                    text = "${item.hostname} (${item.host}:${item.wsPort})",
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                                    fontSize = 13.sp,
                                    color = AccentBlue,
                                )
                            }
                        }
                    }
                }

                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it.trim() },
                    label = { Text("电脑局域网 IP (如 192.168.1.10)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = wsPort,
                        onValueChange = { wsPort = it.filter(Char::isDigit) },
                        label = { Text("WS 端口") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = udpPort,
                        onValueChange = { udpPort = it.filter(Char::isDigit) },
                        label = { Text("UDP 端口") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                }

                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it.trim() },
                    label = { Text("6位配对码 Token") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                HorizontalDivider(color = BorderSubtle)

                Column {
                    Text(
                        text = String.format(Locale.US, "触控板灵敏度: %.1fx", sensitivity),
                        fontSize = 13.sp,
                        color = TextSecondary,
                    )
                    Slider(
                        value = sensitivity,
                        onValueChange = { sensitivity = it },
                        valueRange = 0.6f..3.2f,
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("反转滚轮方向（自然滚动）", fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        Text(
                            if (naturalScroll) "当前：双指上滑内容上滚" else "当前：传统鼠标滚轮方向",
                            fontSize = 11.sp,
                            color = TextSecondary,
                        )
                    }
                    Switch(checked = naturalScroll, onCheckedChange = { naturalScroll = it })
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("音量键盲操", fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        Text("音量- 按住录音，音量+ 快捷发送", fontSize = 11.sp, color = TextSecondary)
                    }
                    Switch(checked = volumeBlind, onCheckedChange = { volumeBlind = it })
                }

                if (volumeBlind) {
                    Spacer(modifier = Modifier.height(2.dp))
                    Text("「音量+」映射动作：", fontSize = 12.sp, color = TextSecondary)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        VolumeUpAction.entries.forEach { act ->
                            val selected = act == volumeUpAction
                            Surface(
                                color = if (selected) AccentBlue else SurfaceElevated,
                                shape = RoundedCornerShape(8.dp),
                                modifier = Modifier
                                    .weight(1f)
                                    .clickable { volumeUpAction = act },
                            ) {
                                Text(
                                    text = act.label.substringBefore(" "),
                                    fontSize = 11.sp,
                                    modifier = Modifier.padding(vertical = 7.dp, horizontal = 4.dp),
                                    color = TextPrimary,
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val updated = initialConfig.copy(
                        host = host.trim(),
                        wsPort = wsPort.toIntOrNull() ?: 8765,
                        udpPort = udpPort.toIntOrNull() ?: 8766,
                        token = token.trim(),
                        sensitivity = sensitivity,
                        naturalScroll = naturalScroll,
                        volumeKeyBlindMode = volumeBlind,
                        volumeUpAction = volumeUpAction,
                    )
                    onApplyAndConnect(updated)
                },
            ) {
                Text("保存并连接")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    )
}

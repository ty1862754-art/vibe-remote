package com.viberemote.app.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import com.viberemote.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

data class ReleaseUpdate(
    val latestVersion: String,
    val hasUpdate: Boolean,
    val releaseUrl: String,
    val apkName: String?,
    val apkDownloadUrl: String?,
    val apkApiUrl: String?,
    val notes: String,
)

object UpdateManager {
    private const val GITHUB_REPO = "ty1862754-art/vibe-remote"

    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    fun isNewerVersion(latest: String, current: String): Boolean {
        val a = parseVersion(latest)
        val b = parseVersion(current)
        val maxLen = maxOf(a.size, b.size)
        for (i in 0 until maxLen) {
            val av = a.getOrElse(i) { 0 }
            val bv = b.getOrElse(i) { 0 }
            if (av != bv) return av > bv
        }
        return false
    }

    private fun parseVersion(raw: String): List<Int> {
        val cleaned = raw.trim().removePrefix("v").removePrefix("V")
        return Regex("\\d+").findAll(cleaned).mapNotNull { it.value.toIntOrNull() }.toList().ifEmpty { listOf(0) }
    }

    suspend fun checkLatestRelease(githubToken: String = ""): Result<ReleaseUpdate> = withContext(Dispatchers.IO) {
        runCatching {
            val reqBuilder = Request.Builder()
                .url("https://api.github.com/repos/$GITHUB_REPO/releases/latest")
                .header("Accept", "application/vnd.github+json")
                .header("User-Agent", "VibeRemote/${BuildConfig.VERSION_NAME}")
            if (githubToken.isNotBlank()) {
                reqBuilder.header("Authorization", "Bearer ${githubToken.trim()}")
            }

            client.newCall(reqBuilder.build()).execute().use { resp ->
                if (resp.code == 404) {
                    error("未找到 Release（如仓库为私有，请填写 GitHub Token 或将仓库设为公开）")
                }
                if (!resp.isSuccessful) {
                    error("GitHub 接口返回 ${resp.code}")
                }
                val body = resp.body?.string().orEmpty()
                val json = JSONObject(body)
                val tag = json.optString("tag_name").trim()
                val latestVer = tag.removePrefix("v").removePrefix("V").ifBlank { BuildConfig.VERSION_NAME }
                val releaseUrl = json.optString("html_url").ifBlank { "https://github.com/$GITHUB_REPO/releases" }
                val notes = json.optString("body").trim()

                var apkName: String? = null
                var apkDownloadUrl: String? = null
                var apkApiUrl: String? = null
                val assets = json.optJSONArray("assets")
                if (assets != null) {
                    for (i in 0 until assets.length()) {
                        val item = assets.optJSONObject(i) ?: continue
                        val name = item.optString("name")
                        if (name.endsWith(".apk", ignoreCase = true)) {
                            apkName = name
                            apkDownloadUrl = item.optString("browser_download_url").takeIf { it.isNotBlank() }
                            apkApiUrl = item.optString("url").takeIf { it.isNotBlank() }
                            break
                        }
                    }
                }

                ReleaseUpdate(
                    latestVersion = latestVer,
                    hasUpdate = isNewerVersion(latestVer, BuildConfig.VERSION_NAME),
                    releaseUrl = releaseUrl,
                    apkName = apkName,
                    apkDownloadUrl = apkDownloadUrl,
                    apkApiUrl = apkApiUrl,
                    notes = notes,
                )
            }
        }
    }

    suspend fun downloadApk(
        context: Context,
        release: ReleaseUpdate,
        githubToken: String = "",
        onProgress: (Float) -> Unit,
    ): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val useApi = githubToken.isNotBlank() && !release.apkApiUrl.isNullOrBlank()
            val url = if (useApi) release.apkApiUrl!! else release.apkDownloadUrl
            require(!url.isNullOrBlank()) { "该 Release 中未找到 APK 安装包" }

            val reqBuilder = Request.Builder()
                .url(url)
                .header("User-Agent", "VibeRemote/${BuildConfig.VERSION_NAME}")
            if (useApi) {
                reqBuilder.header("Accept", "application/octet-stream")
                reqBuilder.header("Authorization", "Bearer ${githubToken.trim()}")
            }

            val updatesDir = File(context.cacheDir, "updates").apply { mkdirs() }
            val outFile = File(updatesDir, release.apkName ?: "viberemote-latest.apk")

            client.newCall(reqBuilder.build()).execute().use { resp ->
                if (!resp.isSuccessful) {
                    error("下载失败 (HTTP ${resp.code})")
                }
                val body = resp.body ?: error("响应内容为空")
                val total = body.contentLength()
                body.byteStream().use { input ->
                    outFile.outputStream().use { output ->
                        val buf = ByteArray(16 * 1024)
                        var copied = 0L
                        while (true) {
                            val read = input.read(buf)
                            if (read <= 0) break
                            output.write(buf, 0, read)
                            copied += read
                            if (total > 0) {
                                onProgress((copied.toFloat() / total.toFloat()).coerceIn(0f, 1f))
                            }
                        }
                    }
                }
            }
            onProgress(1f)
            outFile
        }
    }

    fun launchApkInstaller(context: Context, apkFile: File): Boolean {
        if (!context.packageManager.canRequestPackageInstalls()) {
            val permIntent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(permIntent)
            return false
        }

        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apkFile,
        )
        val installIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(installIntent)
        return true
    }
}

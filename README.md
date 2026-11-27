# VibeRemote — 安卓 Wi-Fi 无线触控板 & Vibe Coding 语音控制器

把你的安卓手机变成一个 **低延迟无线触控板 + 物理音量键盲操语音输入器 + Vibe Coding 快捷遥控器**，局域网直连 Windows 电脑，完全本地离线识别（`sherpa-onnx + SenseVoiceSmall`）。

## 核心功能

- **低延迟大触控板（UDP 通道）**：单指移动（带加速度曲线）、轻点左键、双击按住拖拽、双指滑动滚轮、双指轻点右键、三指轻点中键。
- **音量键盲操语音转文字（WebSocket 音频流）**：
  - **按住「音量 -」**：震动 1 下开始录音 → 松手立即发送给电脑本地 **SenseVoiceSmall** 离线识别（中英混说编程词极准、自动加标点）→ 自动备份剪贴板并 `Ctrl+V` 无乱码上屏（可选自动回车）→ 手机双震确认。
  - **短按「音量 +」**：快捷触发 `Enter`（可在 App 内改为 `Ctrl+Z` / `Tab` / `Esc`）。
  - **防误触盲操模式**：一键压暗屏幕并锁定触控板，只保留物理音量键说话。
- **Vibe Coding 快捷宏栏**：`左键 / 右键 / Enter / 撤销(Ctrl+Z) / Esc / Tab / 退格 / 全选 / 切窗口(Alt+Tab) / Ctrl+Enter`。
- **桌面非抢焦点状态浮窗**：录音、识别中、已上屏结果直接浮在电脑屏幕底部，**不抢走 IDE / 终端焦点**。
- **可选 AI 润色**：在 `config.toml` 中填入任意 OpenAI 兼容接口（DeepSeek / OpenAI / 硅基流动 / 本地 Ollama 等），打开手机端「AI润色」开关即可自动去口癖、修正代码术语。

---

## 目录结构

```text
├── pc-server/                 # Windows 服务端 (Python 3.13 + uv + sherpa-onnx)
├── android-app/               # 原生安卓 App (Kotlin + Jetpack Compose)
└── .github/workflows/
    └── build-android-apk.yml  # GitHub Actions 云端自动打 APK（无需本机装 Android Studio）
```

---

## 第一步：在目标 Windows 电脑上运行服务端（两种方式任选）

### 方式 A：下载免安装绿色版（推荐给另一台电脑，无需装 Python / uv）

1. 将本仓库推送到 GitHub 后，打开仓库顶部 **Actions → Build Windows Server (Portable ZIP)**。
2. 下载底部 Artifacts 中的 `VibeRemote-Windows-Portable.zip`，传到另一台 Windows 电脑解压。
3. 直接双击 **`VibeRemoteServer.exe`** 即可启动！
   - 首次运行会自动下载 `SenseVoiceSmall (int8)` 模型（约 150MB）到同目录 `models/` 文件夹。
   - 如手机连不上，双击同目录的 **`放行防火墙.bat`** 放行端口即可。

### 方式 B：从源码一键运行（适合开发调试）

复制 `pc-server/` 文件夹（或 `git clone` 仓库）到另一台 Windows 电脑，直接双击 **`pc-server/启动服务端.bat`**（会自动检测安装 `uv`、同步依赖并启动），或者在终端手动执行：

```powershell
cd pc-server
uv sync
uv run vibe-server
```

> **如果 GitHub 模型下载较慢**：
> 复制 `config.example.toml` 为 `config.toml`，修改 `model_url` 为镜像地址，或手动下载解压到 `models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/`。

启动成功后，终端会直接打印**配对二维码**、局域网 IP 和 6 位配对码，你也可以浏览器打开 `http://<你的IP>:8765/pair` 查看高清二维码。

---

## 第二步：通过 GitHub Actions 获取安卓 APK（无需本机装 Android Studio）

1. 在 GitHub 创建一个仓库（私有/公开均可），将本项目推送上去：
   ```powershell
   git init
   git add .
   git commit -m "init VibeRemote"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<你的仓库名>.git
   git push -u origin main
   ```
2. 打开仓库页面 → 点击顶部 **Actions** → 等待 `Build Android APK` 运行完成（约 2~3 分钟）。
3. 进入本次运行记录，在底部 **Artifacts** 下载 `VibeRemote-Android-APK`（解压得到 `app-debug.apk`），传到安卓手机安装即可。
   - 也可以在 GitHub Actions 页面手动点 **Run workflow** 随时触发重新构建。

---

## 第三步：扫码连接开始使用

1. 打开手机上的 **VibeRemote**，点「扫码一键配对」，扫描电脑终端或 `/pair` 页面的二维码（或点「搜索局域网」后填入 6 位配对码）。
2. 把电脑光标点进 Cursor / VS Code / Antigravity / 终端对话框。
3. **按住手机「音量 -」说话，松手即自动上屏**！

> **还没拿到 APK 前想先体验电脑端？**
> 手机浏览器直接访问电脑启动日志里打印的 `网页调试端` 链接（`http://<IP>:8765/debug?token=<配对码>`），可立刻测试触控板控鼠与快捷发送文本。

---

## 自定义热词与 AI 润色

复制 `pc-server/config.example.toml` 为 `pc-server/config.toml` 后按需修改：

- `[asr.hotwords]`：添加你常用的项目词或易错词替换。
- `[llm_polish]`：将 `enabled = true` 并填写 `base_url`、`api_key`、`model`，重启服务端后即可在手机端开启「AI润色」。

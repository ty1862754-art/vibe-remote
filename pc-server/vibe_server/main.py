from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import qrcode
import qrcode.image.svg
import uvicorn
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .asr_engine import SenseVoiceAsrEngine
from .config import AppConfig, get_lan_ip, load_config
from .overlay import StatusOverlay
from .state_hub import ServerStateHub
from .tray import SystemTrayController, set_console_visible
from .udp_server import start_udp_server
from .updater import check_latest_release, download_windows_update
from .win_input import WindowsInputController, is_admin

logger = logging.getLogger(__name__)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    WEB_DEBUG_PATH = Path(sys._MEIPASS) / "vibe_server" / "web_debug.html"
else:
    WEB_DEBUG_PATH = Path(__file__).resolve().parent / "web_debug.html"


def build_pair_uri(ip: str, ws_port: int, udp_port: int, token: str) -> str:
    return f"viberemote://connect?host={quote(ip)}&port={ws_port}&udp={udp_port}&token={quote(token)}"


def print_terminal_qr(uri: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(uri)
    qr.make(fit=True)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    print(buf.getvalue())


def render_qr_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")


def create_app(
    cfg: AppConfig | None = None,
    *,
    auto_download_model: bool = True,
    skip_asr_load: bool = False,
    start_udp: bool = True,
    on_tray_quit=None,
    state_hub: ServerStateHub | None = None,
    gui_mode: bool = False,
) -> FastAPI:
    app_cfg = cfg or load_config()
    controller = WindowsInputController(
        mouse_sensitivity=app_cfg.input.mouse_sensitivity,
        scroll_sensitivity=app_cfg.input.scroll_sensitivity,
        clipboard_restore_delay_ms=app_cfg.input.clipboard_restore_delay_ms,
    )
    asr_engine = SenseVoiceAsrEngine(app_cfg.asr, app_cfg.llm_polish)
    standalone_overlay = StatusOverlay(enabled=app_cfg.server.enable_overlay and not gui_mode)
    active_clients = {"count": 0}

    def show_overlay(state: str, message: str = "", auto_hide_ms: int = 0) -> None:
        if gui_mode and state_hub is not None:
            state_hub.push_overlay(state, message, auto_hide_ms)
        else:
            standalone_overlay.show(state, message, auto_hide_ms)

    def hide_overlay() -> None:
        if gui_mode and state_hub is not None:
            state_hub.push_overlay("hide", "", 0)
        else:
            standalone_overlay.hide()

    controller.on_uipi_blocked = lambda: (
        show_overlay("error", "⚠ 当前窗口为管理员权限，请提权管理员重启", auto_hide_ms=3500),
        state_hub.push_log("⚠ 目标窗口为管理员权限，请点击顶部「点此提权」或托盘以管理员重启") if state_hub else None,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        standalone_overlay.start()
        udp_transport = None
        if start_udp:
            udp_transport = await start_udp_server(app_cfg, controller)

        async def load_asr_async() -> None:
            if state_hub is not None:
                state_hub.set_asr("loading", "⏳ 正在加载/下载 SenseVoiceSmall 模型...")
            ok = await asyncio.to_thread(asr_engine.load, auto_download_model)
            if state_hub is not None:
                if ok:
                    state_hub.set_asr("ready", "✅ SenseVoiceSmall 离线模型就绪")
                    state_hub.push_log("✅ SenseVoiceSmall 离线语音模型已加载就绪。")
                else:
                    err = asr_engine.load_error or "模型加载失败"
                    state_hub.set_asr("error", f"⚠ {err}")
                    state_hub.push_log(f"⚠ 语音模型加载失败: {err}")

        if not skip_asr_load:
            asyncio.create_task(load_asr_async())

        lan_ip = get_lan_ip()
        pair_uri = build_pair_uri(
            lan_ip, app_cfg.server.ws_port, app_cfg.server.udp_port, app_cfg.server.token
        )
        pair_url = f"http://{lan_ip}:{app_cfg.server.ws_port}/pair"
        if not gui_mode:
            print("\n" + "=" * 60)
            print(f"  VibeRemote Server v{__version__} 已启动")
            print("=" * 60)
            print(f"  局域网 IP   : {lan_ip}")
            print(f"  WS 端口     : {app_cfg.server.ws_port}")
            print(f"  UDP 端口    : {app_cfg.server.udp_port}")
            print(f"  配对码      : {app_cfg.server.token}")
            print(f"  运行权限    : {'管理员（可控制所有软件窗口）' if is_admin() else '普通权限（遇到管理员软件失灵时，请右键托盘选择「以管理员权限重启」）'}")
            print(f"  扫码页      : {pair_url}")
            print(f"  网页调试端  : http://{lan_ip}:{app_cfg.server.ws_port}/debug?token={app_cfg.server.token}")
            print("=" * 60)
            print("  使用 Android App 扫描下方二维码一键连接（右键右下角托盘图标可隐藏窗口/设置开机自启）：\n")
            print_terminal_qr(pair_uri)

        def handle_tray_check_update() -> None:
            show_overlay("transcribing", "🔍 正在检查 GitHub 最新版本...")
            try:
                info = check_latest_release(app_cfg.update, __version__)
                if not info.has_update:
                    show_overlay("done", f"✅ 已是最新版本 v{info.current_version}", auto_hide_ms=2500)
                    if state_hub:
                        state_hub.push_log(f"✅ 当前已是最新版本 v{info.current_version}")
                    return
                show_overlay("polishing", f"⬇ 发现 v{info.latest_version}，正在下载安装包...")
                try:
                    zip_path = download_windows_update(info, app_cfg.update)
                    show_overlay("done", f"✅ 已下载到 updates/{zip_path.name}", auto_hide_ms=3500)
                    if state_hub:
                        state_hub.push_log(f"✅ 已下载新版到 {zip_path}")
                    if sys.platform == "win32":
                        os.startfile(str(zip_path.parent))  # type: ignore[attr-defined]
                except Exception:
                    show_overlay("done", f"🆕 发现 v{info.latest_version}，已打开下载页", auto_hide_ms=3000)
                    webbrowser.open(info.release_url)
            except Exception as exc:
                logger.warning("检查更新失败: %s", exc)
                show_overlay("error", f"⚠ 检查更新失败: {exc}", auto_hide_ms=3500)
                if state_hub:
                    state_hub.push_log(f"⚠ 检查更新失败: {exc}")

        tray = SystemTrayController(
            enabled=app_cfg.server.enable_tray,
            pair_url=pair_url,
            display_endpoint=f"{lan_ip}:{app_cfg.server.ws_port}",
            on_quit=on_tray_quit or (lambda: None),
            on_check_update=handle_tray_check_update,
            on_show_window=state_hub.request_show_window if (gui_mode and state_hub is not None) else None,
        )
        tray.start()
        if not gui_mode and app_cfg.server.start_minimized:
            set_console_visible(False)

        yield

        tray.stop()
        if udp_transport is not None:
            udp_transport.close()
        standalone_overlay.stop()

    app = FastAPI(title="VibeRemote PC Server", version=__version__, lifespan=lifespan)
    app.state.cfg = app_cfg
    app.state.controller = controller
    app.state.asr_engine = asr_engine
    app.state.overlay = standalone_overlay

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "asr_ready": asr_engine.is_ready,
                "asr_error": asr_engine.load_error,
                "llm_polish_available": app_cfg.llm_polish.is_available,
            }
        )

    @app.get("/update/check")
    async def check_update() -> JSONResponse:
        try:
            info = await asyncio.to_thread(check_latest_release, app_cfg.update, __version__)
            return JSONResponse(
                {
                    "current_version": info.current_version,
                    "latest_version": info.latest_version,
                    "has_update": info.has_update,
                    "release_url": info.release_url,
                    "windows_download_url": info.windows_download_url,
                    "android_download_url": info.android_download_url,
                    "notes": info.notes,
                }
            )
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)

    @app.get("/pair", response_class=HTMLResponse)
    async def pair_page() -> HTMLResponse:
        lan_ip = get_lan_ip()
        pair_uri = build_pair_uri(
            lan_ip, app_cfg.server.ws_port, app_cfg.server.udp_port, app_cfg.server.token
        )
        svg = render_qr_svg(pair_uri)
        debug_url = f"http://{lan_ip}:{app_cfg.server.ws_port}/debug?token={app_cfg.server.token}"
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>VibeRemote 扫码配对</title>
<style>
body {{ font-family: system-ui, sans-serif; background:#0f1117; color:#f3f4f6;
display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
.card {{ background:#181c26; padding:28px 36px; border-radius:18px; text-align:center; border:1px solid #2a3040; }}
.qr {{ background:#fff; padding:14px; border-radius:12px; display:inline-block; margin:16px 0; }}
code {{ background:#11131a; padding:4px 8px; border-radius:6px; color:#60a5fa; }}
a {{ color:#60a5fa; }}
</style></head><body>
<div class="card">
  <h2>VibeRemote 扫码连接</h2>
  <div class="qr">{svg}</div>
  <p>IP: <code>{lan_ip}</code> · WS: <code>{app_cfg.server.ws_port}</code> · UDP: <code>{app_cfg.server.udp_port}</code></p>
  <p>配对码 Token: <code>{app_cfg.server.token}</code></p>
  <p style="font-size:13px;color:#9ca3af;">未装 APK 时也可先用手机打开 <a href="{debug_url}">网页调试端</a></p>
</div></body></html>"""
        return HTMLResponse(html)

    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page() -> HTMLResponse:
        return HTMLResponse(WEB_DEBUG_PATH.read_text(encoding="utf-8"))

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket, token: str = Query(default="")) -> None:
        if token != app_cfg.server.token:
            await ws.close(code=4001, reason="Invalid pairing token")
            return

        await ws.accept()
        client_host = ws.client.host if ws.client else "unknown"
        active_clients["count"] += 1
        logger.info("手机客户端已连接: %s", client_host)
        if state_hub is not None:
            state_hub.set_clients(active_clients["count"], client_host)
            state_hub.push_log(f"📱 手机已连接 ({client_host})")

        await ws.send_json(
            {
                "type": "hello",
                "version": __version__,
                "asr_ready": asr_engine.is_ready,
                "asr_error": asr_engine.load_error,
                "asr_engine": "sensevoice",
                "llm_polish_enabled": app_cfg.llm_polish.is_available,
                "udp_port": app_cfg.server.udp_port,
            }
        )

        audio_buf = bytearray()
        audio_active = False
        audio_sample_rate = 16000
        audio_auto_enter = False
        audio_polish = False
        audio_session_id = 0
        partial_task: asyncio.Task | None = None

        async def cancel_partial_task() -> None:
            nonlocal partial_task
            if partial_task is not None and not partial_task.done():
                partial_task.cancel()
                try:
                    await partial_task
                except asyncio.CancelledError:
                    pass
            partial_task = None

        async def run_partial_loop(session_id: int) -> None:
            last_len = 0
            last_text = ""
            try:
                while audio_active and session_id == audio_session_id:
                    await asyncio.sleep(0.75)
                    if not audio_active or session_id != audio_session_id:
                        break
                    cur_len = len(audio_buf)
                    if not asr_engine.is_ready or cur_len - last_len < int(audio_sample_rate * 2 * 0.35):
                        continue
                    snapshot = bytes(audio_buf)
                    last_len = cur_len
                    preview = await asyncio.to_thread(
                        asr_engine.transcribe_partial_pcm16,
                        snapshot,
                        audio_sample_rate,
                    )
                    if (
                        audio_active
                        and session_id == audio_session_id
                        and preview
                        and preview != last_text
                    ):
                        last_text = preview
                        await ws.send_json({"type": "partial_transcript", "text": preview})
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("partial ASR preview skipped: %s", exc)

        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break

                if msg.get("bytes") is not None:
                    if audio_active:
                        audio_buf.extend(msg["bytes"])
                    continue

                raw_text = msg.get("text")
                if not raw_text:
                    continue

                try:
                    data = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "ping":
                    await ws.send_json(
                        {
                            "type": "pong",
                            "asr_ready": asr_engine.is_ready,
                        }
                    )
                elif msg_type == "move":
                    controller.move_mouse(float(data.get("dx", 0)), float(data.get("dy", 0)))
                elif msg_type == "scroll":
                    controller.scroll(float(data.get("dx", 0)), float(data.get("dy", 0)))
                elif msg_type == "click":
                    controller.mouse_click(
                        button=str(data.get("button", "left")),
                        action=str(data.get("action", "click")),
                    )
                elif msg_type == "key":
                    keys = data.get("keys")
                    if isinstance(keys, list) and keys:
                        controller.press_keys([str(k) for k in keys])
                elif msg_type == "text":
                    text = str(data.get("text", ""))
                    auto_enter = bool(data.get("auto_enter", False))
                    if text:
                        ok = await asyncio.to_thread(controller.paste_text, text, auto_enter)
                        show_overlay("done", f"✅ 已输入: {text}", auto_hide_ms=2000)
                        if state_hub is not None:
                            state_hub.push_log(f"⌨ 已输入: {text}")
                        await ws.send_json(
                            {
                                "type": "transcript",
                                "mode": "send",
                                "raw_text": text,
                                "final_text": text,
                                "pasted": ok,
                                "latency_ms": 0,
                            }
                        )
                elif msg_type == "audio_start":
                    await cancel_partial_task()
                    audio_session_id += 1
                    audio_buf.clear()
                    audio_active = True
                    audio_sample_rate = int(data.get("sample_rate", 16000))
                    audio_auto_enter = bool(data.get("auto_enter", False))
                    audio_polish = bool(data.get("polish", False))
                    show_overlay("recording", "🎙 正在录音...")
                    await ws.send_json({"type": "status", "state": "recording", "message": "正在录音"})
                    partial_task = asyncio.create_task(run_partial_loop(audio_session_id))
                elif msg_type == "audio_cancel":
                    audio_active = False
                    audio_session_id += 1
                    await cancel_partial_task()
                    audio_buf.clear()
                    hide_overlay()
                    await ws.send_json({"type": "status", "state": "idle", "message": "已取消发送"})
                elif msg_type == "audio_end":
                    audio_active = False
                    audio_session_id += 1
                    await cancel_partial_task()
                    end_mode = str(data.get("mode", "send")).strip().lower()
                    if end_mode not in ("send", "edit"):
                        end_mode = "send"
                    pcm_payload = bytes(audio_buf)
                    audio_buf.clear()

                    if len(pcm_payload) < int(audio_sample_rate * 2 * 0.15):
                        hide_overlay()
                        await ws.send_json(
                            {"type": "status", "state": "idle", "message": "录音太短，已忽略"}
                        )
                        continue

                    if not asr_engine.is_ready:
                        err = asr_engine.load_error or "本地模型正在加载/下载，请稍候"
                        show_overlay("error", f"⚠ {err}", auto_hide_ms=2500)
                        await ws.send_json({"type": "status", "state": "error", "message": err})
                        continue

                    show_overlay(
                        "polishing" if (audio_polish and app_cfg.llm_polish.is_available) else "transcribing",
                        "⏳ 语音识别中...",
                    )
                    await ws.send_json({"type": "status", "state": "transcribing", "message": "识别中..."})

                    try:
                        res = await asyncio.to_thread(
                            asr_engine.transcribe_pcm16,
                            pcm_payload,
                            audio_sample_rate,
                            audio_polish,
                        )
                    except Exception as exc:
                        logger.exception("ASR 识别出错: %s", exc)
                        show_overlay("error", f"⚠ 识别出错: {exc}", auto_hide_ms=2500)
                        await ws.send_json({"type": "status", "state": "error", "message": str(exc)})
                        continue

                    if not res.final_text:
                        hide_overlay()
                        await ws.send_json(
                            {"type": "status", "state": "idle", "message": "未识别到有效语音"}
                        )
                        continue

                    if end_mode == "edit":
                        show_overlay("polishing", "✏ 请在手机端编辑文字...", auto_hide_ms=1800)
                        logger.info("ASR 完成 (%dms, 等待手机编辑): %s", res.latency_ms, res.final_text)
                        if state_hub is not None:
                            state_hub.push_log(f"✏ 识别待编辑 ({res.latency_ms}ms): {res.final_text}")
                        await ws.send_json(
                            {
                                "type": "transcript",
                                "mode": "edit",
                                "raw_text": res.raw_text,
                                "final_text": res.final_text,
                                "pasted": False,
                                "latency_ms": res.latency_ms,
                                "polished": res.polished,
                            }
                        )
                        continue

                    pasted = await asyncio.to_thread(
                        controller.paste_text, res.final_text, audio_auto_enter
                    )
                    show_overlay("done", f"✅ {res.final_text}", auto_hide_ms=2200)
                    logger.info(
                        "ASR 完成 (%dms%s): %s",
                        res.latency_ms,
                        ", LLM润色" if res.polished else "",
                        res.final_text,
                    )
                    if state_hub is not None:
                        state_hub.push_log(f"🎙 已上屏 ({res.latency_ms}ms): {res.final_text}")
                    await ws.send_json(
                        {
                            "type": "transcript",
                            "mode": "send",
                            "raw_text": res.raw_text,
                            "final_text": res.final_text,
                            "pasted": pasted,
                            "latency_ms": res.latency_ms,
                            "polished": res.polished,
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            audio_active = False
            await cancel_partial_task()
            hide_overlay()
            active_clients["count"] = max(0, active_clients["count"] - 1)
            logger.info("手机客户端已断开: %s", client_host)
            if state_hub is not None:
                state_hub.set_clients(active_clients["count"], "")
                state_hub.push_log(f"📱 手机已断开 ({client_host})")

    return app


def _ensure_std_streams() -> None:
    """Guard against sys.stdout/stderr being None in PyInstaller --windowed builds."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def cli() -> None:
    _ensure_std_streams()
    parser = argparse.ArgumentParser(description="VibeRemote Windows Desktop App & Server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml")
    parser.add_argument("--cli", action="store_true", help="Run in terminal/console mode without desktop GUI")
    parser.add_argument("--no-overlay", action="store_true", help="Disable Windows floating overlay")
    parser.add_argument("--no-tray", action="store_true", help="Disable Windows system tray icon")
    parser.add_argument("--minimized", action="store_true", help="Start minimized to system tray")
    parser.add_argument("--no-download", action="store_true", help="Do not auto-download ASR model")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_config(args.config)
    if args.no_overlay:
        cfg.server.enable_overlay = False
    if args.no_tray:
        cfg.server.enable_tray = False
    if args.minimized:
        cfg.server.start_minimized = True

    server_ref: list[uvicorn.Server] = []
    use_gui = (not args.cli) and sys.platform == "win32"

    if use_gui:
        try:
            from .desktop_app import VibeRemoteDesktopApp
        except Exception as exc:
            logger.warning("无法启动桌面 GUI，自动回退命令行模式: %s", exc)
            use_gui = False

    if not use_gui:
        def request_shutdown() -> None:
            if server_ref:
                server_ref[0].should_exit = True

        app = create_app(
            cfg,
            auto_download_model=not args.no_download,
            on_tray_quit=request_shutdown,
            gui_mode=False,
        )
        uv_config = uvicorn.Config(
            app, host=cfg.server.host, port=cfg.server.ws_port, log_level="warning", log_config=None
        )
        server = uvicorn.Server(uv_config)
        server_ref.append(server)
        server.run()
        return

    hub = ServerStateHub()

    def request_gui_shutdown() -> None:
        if server_ref:
            server_ref[0].should_exit = True
        hub.request_quit()

    app = create_app(
        cfg,
        auto_download_model=not args.no_download,
        on_tray_quit=request_gui_shutdown,
        state_hub=hub,
        gui_mode=True,
    )
    uv_config = uvicorn.Config(
        app, host=cfg.server.host, port=cfg.server.ws_port, log_level="warning", log_config=None
    )
    server = uvicorn.Server(uv_config)
    server_ref.append(server)

    server_thread = threading.Thread(target=server.run, name="vibe-uvicorn", daemon=True)
    server_thread.start()

    lan_ip = get_lan_ip()
    pair_uri = build_pair_uri(lan_ip, cfg.server.ws_port, cfg.server.udp_port, cfg.server.token)
    pair_url = f"http://{lan_ip}:{cfg.server.ws_port}/pair"
    debug_url = f"http://{lan_ip}:{cfg.server.ws_port}/debug?token={cfg.server.token}"

    gui = VibeRemoteDesktopApp(
        cfg=cfg,
        hub=hub,
        lan_ip=lan_ip,
        pair_uri=pair_uri,
        pair_url=pair_url,
        debug_url=debug_url,
        on_quit=request_gui_shutdown,
        start_minimized=cfg.server.start_minimized,
    )
    try:
        gui.run()
    finally:
        server.should_exit = True
        server_thread.join(timeout=2.0)


if __name__ == "__main__":
    cli()

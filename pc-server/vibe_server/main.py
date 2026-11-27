from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
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
from .udp_server import start_udp_server
from .win_input import WindowsInputController

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
) -> FastAPI:
    app_cfg = cfg or load_config()
    controller = WindowsInputController(
        mouse_sensitivity=app_cfg.input.mouse_sensitivity,
        scroll_sensitivity=app_cfg.input.scroll_sensitivity,
        clipboard_restore_delay_ms=app_cfg.input.clipboard_restore_delay_ms,
    )
    asr_engine = SenseVoiceAsrEngine(app_cfg.asr, app_cfg.llm_polish)
    overlay = StatusOverlay(enabled=app_cfg.server.enable_overlay)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        overlay.start()
        udp_transport = None
        if start_udp:
            udp_transport = await start_udp_server(app_cfg, controller)

        if not skip_asr_load:
            asyncio.create_task(asyncio.to_thread(asr_engine.load, auto_download_model))

        lan_ip = get_lan_ip()
        pair_uri = build_pair_uri(
            lan_ip, app_cfg.server.ws_port, app_cfg.server.udp_port, app_cfg.server.token
        )
        print("\n" + "=" * 60)
        print(f"  VibeRemote Server v{__version__} 已启动")
        print("=" * 60)
        print(f"  局域网 IP   : {lan_ip}")
        print(f"  WS 端口     : {app_cfg.server.ws_port}")
        print(f"  UDP 端口    : {app_cfg.server.udp_port}")
        print(f"  配对码      : {app_cfg.server.token}")
        print(f"  扫码页      : http://{lan_ip}:{app_cfg.server.ws_port}/pair")
        print(f"  网页调试端  : http://{lan_ip}:{app_cfg.server.ws_port}/debug?token={app_cfg.server.token}")
        print("=" * 60)
        print("  使用 Android App 扫描下方二维码一键连接：\n")
        print_terminal_qr(pair_uri)

        yield

        if udp_transport is not None:
            udp_transport.close()
        overlay.stop()

    app = FastAPI(title="VibeRemote PC Server", version=__version__, lifespan=lifespan)
    app.state.cfg = app_cfg
    app.state.controller = controller
    app.state.asr_engine = asr_engine
    app.state.overlay = overlay

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
        logger.info("手机客户端已连接: %s", client_host)

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
                        overlay.show("done", f"✅ 已输入: {text}", auto_hide_ms=2000)
                        await ws.send_json(
                            {
                                "type": "transcript",
                                "raw_text": text,
                                "final_text": text,
                                "pasted": ok,
                                "latency_ms": 0,
                            }
                        )
                elif msg_type == "audio_start":
                    audio_buf.clear()
                    audio_active = True
                    audio_sample_rate = int(data.get("sample_rate", 16000))
                    audio_auto_enter = bool(data.get("auto_enter", False))
                    audio_polish = bool(data.get("polish", False))
                    overlay.show("recording", "🎙 正在录音...")
                    await ws.send_json({"type": "status", "state": "recording", "message": "正在录音"})
                elif msg_type == "audio_cancel":
                    audio_buf.clear()
                    audio_active = False
                    overlay.hide()
                    await ws.send_json({"type": "status", "state": "idle", "message": "已取消"})
                elif msg_type == "audio_end":
                    audio_active = False
                    pcm_payload = bytes(audio_buf)
                    audio_buf.clear()

                    if len(pcm_payload) < int(audio_sample_rate * 2 * 0.15):
                        overlay.hide()
                        await ws.send_json(
                            {"type": "status", "state": "idle", "message": "录音太短，已忽略"}
                        )
                        continue

                    if not asr_engine.is_ready:
                        err = asr_engine.load_error or "本地模型正在加载/下载，请稍候"
                        overlay.show("error", f"⚠ {err}", auto_hide_ms=2500)
                        await ws.send_json({"type": "status", "state": "error", "message": err})
                        continue

                    overlay.show(
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
                        overlay.show("error", f"⚠ 识别出错: {exc}", auto_hide_ms=2500)
                        await ws.send_json({"type": "status", "state": "error", "message": str(exc)})
                        continue

                    if not res.final_text:
                        overlay.hide()
                        await ws.send_json(
                            {"type": "status", "state": "idle", "message": "未识别到有效语音"}
                        )
                        continue

                    pasted = await asyncio.to_thread(
                        controller.paste_text, res.final_text, audio_auto_enter
                    )
                    overlay.show("done", f"✅ {res.final_text}", auto_hide_ms=2200)
                    logger.info(
                        "ASR 完成 (%dms%s): %s",
                        res.latency_ms,
                        ", LLM润色" if res.polished else "",
                        res.final_text,
                    )
                    await ws.send_json(
                        {
                            "type": "transcript",
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
            overlay.hide()
            logger.info("手机客户端已断开: %s", client_host)

    return app


def cli() -> None:
    parser = argparse.ArgumentParser(description="VibeRemote Windows PC Server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml")
    parser.add_argument("--no-overlay", action="store_true", help="Disable Windows floating overlay")
    parser.add_argument("--no-download", action="store_true", help="Do not auto-download ASR model")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cfg = load_config(args.config)
    if args.no_overlay:
        cfg.server.enable_overlay = False

    app = create_app(cfg, auto_download_model=not args.no_download)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.ws_port, log_level="warning")


if __name__ == "__main__":
    cli()

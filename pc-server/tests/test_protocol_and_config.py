from __future__ import annotations

import ctypes
import sys

import numpy as np
from fastapi.testclient import TestClient

from vibe_server.asr_engine import pcm16_bytes_to_float32
from vibe_server.config import AppConfig, ServerConfig, apply_hotwords
from vibe_server.main import build_pair_uri, create_app
from vibe_server.protocol import UdpMousePacket, parse_udp_packet
from vibe_server.win_input import INPUT, resolve_vk


def test_parse_udp_packet() -> None:
    assert parse_udp_packet(b"DISCOVER") == "DISCOVER"
    pkt = parse_udp_packet(b"M|123456|12.5|-4.25")
    assert pkt == UdpMousePacket(kind="M", token="123456", dx=12.5, dy=-4.25)

    scroll_pkt = parse_udp_packet(b"W|123456|0|120")
    assert scroll_pkt == UdpMousePacket(kind="W", token="123456", dx=0.0, dy=120.0)

    # Clamping
    clamped = parse_udp_packet(b"M|123456|99999|-99999")
    assert clamped == UdpMousePacket(kind="M", token="123456", dx=2000.0, dy=-2000.0)

    # Invalid payloads
    assert parse_udp_packet(b"X|123456|1|2") is None
    assert parse_udp_packet(b"M|123456|abc|2") is None
    assert parse_udp_packet(b"garbage") is None


def test_apply_hotwords() -> None:
    hotwords = {"巴格": "bug", "韦伯索克特": "WebSocket", "api": "API"}
    src = "帮我修一下这个巴格，把韦伯索克特和api接口改掉"
    assert apply_hotwords(src, hotwords) == "帮我修一下这个bug，把WebSocket和API接口改掉"


def test_pcm16_conversion() -> None:
    samples_i16 = np.array([0, 16384, -16384, 32767], dtype="<i2")
    out = pcm16_bytes_to_float32(samples_i16.tobytes())
    assert out.dtype == np.float32
    assert len(out) == 4
    assert abs(out[0]) < 1e-6
    assert abs(out[1] - 0.5) < 1e-4
    assert abs(out[2] + 0.5) < 1e-4


def test_win32_input_struct_size_and_vk() -> None:
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(INPUT) == 40
    assert resolve_vk("enter") == 0x0D
    assert resolve_vk("ctrl") == 0x11
    assert resolve_vk("z") == ord("Z")
    assert resolve_vk("nonexistent_key") is None


def test_pair_uri_and_websocket_auth() -> None:
    uri = build_pair_uri("192.168.1.10", 8765, 8766, "654321")
    assert uri == "viberemote://connect?host=192.168.1.10&port=8765&udp=8766&token=654321"

    cfg = AppConfig(server=ServerConfig(token="654321", enable_overlay=False))
    app = create_app(cfg, skip_asr_load=True, start_udp=False)

    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        pair_resp = client.get("/pair")
        assert pair_resp.status_code == 200
        assert "654321" in pair_resp.text

        # Valid token handshake
        with client.websocket_connect("/ws?token=654321") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["udp_port"] == 8766

            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"

from __future__ import annotations

import asyncio
import logging
import socket

from .config import AppConfig
from .protocol import UdpMousePacket, parse_udp_packet
from .win_input import WindowsInputController

logger = logging.getLogger(__name__)


class VibeUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, cfg: AppConfig, controller: WindowsInputController) -> None:
        self.cfg = cfg
        self.controller = controller
        self.transport: asyncio.DatagramTransport | None = None
        self._hostname = socket.gethostname()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        logger.info("UDP 高频触控通道已启动，监听端口 %d", self.cfg.server.udp_port)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        parsed = parse_udp_packet(data)
        if parsed is None:
            return

        if parsed == "DISCOVER":
            if self.transport is not None:
                reply = f"VIBEREMOTE|{self.cfg.server.ws_port}|{self.cfg.server.udp_port}|{self._hostname}"
                self.transport.sendto(reply.encode("utf-8"), addr)
            return

        assert isinstance(parsed, UdpMousePacket)
        if parsed.token != self.cfg.server.token:
            return

        if parsed.kind == "M":
            self.controller.move_mouse(parsed.dx, parsed.dy)
        elif parsed.kind == "W":
            self.controller.scroll(parsed.dx, parsed.dy)

    def error_received(self, exc: Exception) -> None:
        logger.debug("UDP socket error: %s", exc)


async def start_udp_server(
    cfg: AppConfig, controller: WindowsInputController
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: VibeUdpProtocol(cfg, controller),
        local_addr=(cfg.server.host, cfg.server.udp_port),
        allow_broadcast=True,
    )
    return transport

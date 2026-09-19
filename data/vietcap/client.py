"""Connection lifecycle for the unofficial Vietcap Socket.IO endpoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import os

import socketio

from data.vietcap.constants import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_SOCKET_PATH,
    DEFAULT_SOCKET_URL,
    MATCH_PRICE_EVENT,
    SOCKET_TRANSPORTS,
)
from data.vietcap.subscriptions import build_symbol_subscription

logger = logging.getLogger(__name__)


def normalize_socketio_path(path: str) -> str:
    """Return the path format expected by ``python-socketio``."""
    normalized = path.strip().strip("/")
    if not normalized:
        raise ValueError("Socket.IO path must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Observed transport details for an established connection."""

    sid: str
    transport: str


class VietcapRealtimeClient:
    """Manage Vietcap Socket.IO connection and scoped market subscriptions."""

    def __init__(
        self,
        *,
        socket_url: str | None = None,
        socket_path: str | None = None,
        engineio_logger: bool = False,
        socket_client: socketio.Client | None = None,
    ) -> None:
        self.socket_url = socket_url or os.getenv(
            "VIETCAP_SOCKET_URL", DEFAULT_SOCKET_URL
        )
        self.socket_path = normalize_socketio_path(
            socket_path or os.getenv("VIETCAP_SOCKET_PATH", DEFAULT_SOCKET_PATH)
        )
        self._socket = socket_client or socketio.Client(
            reconnection=False,
            logger=engineio_logger,
            engineio_logger=engineio_logger,
        )
        self._socket.on("connect", self._on_connect)
        self._socket.on("disconnect", self._on_disconnect)
        self._socket.on("connect_error", self._on_connect_error)

    @property
    def connected(self) -> bool:
        """Whether the default Socket.IO namespace is connected."""
        return bool(self._socket.connected)

    def connect(
        self, timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    ) -> ConnectionInfo:
        """Connect directly over WebSocket and return observed session metadata."""
        logger.info(
            "Connecting to Vietcap realtime endpoint",
            extra={"socket_url": self.socket_url, "socket_path": self.socket_path},
        )
        try:
            self._socket.connect(
                self.socket_url,
                socketio_path=self.socket_path,
                transports=list(SOCKET_TRANSPORTS),
                wait=True,
                wait_timeout=timeout,
            )
        except Exception:
            logger.exception(
                "Failed to connect to Vietcap realtime endpoint",
                extra={
                    "socket_url": self.socket_url,
                    "socket_path": self.socket_path,
                },
            )
            raise

        if not self.connected:
            raise ConnectionError("Socket.IO connect returned without a connection")

        info = ConnectionInfo(
            sid=self._socket.sid or "",
            transport=self._socket.transport(),
        )
        logger.info(
            "Vietcap realtime connection established",
            extra={"sid": info.sid, "transport": info.transport},
        )
        return info

    def disconnect(self) -> None:
        """Disconnect cleanly if connected."""
        if not self.connected:
            return
        try:
            self._socket.disconnect()
        except Exception:
            logger.exception("Failed to disconnect from Vietcap realtime endpoint")
            raise

    def sleep(self, seconds: float) -> None:
        """Wait while allowing the Socket.IO client to service heartbeats."""
        self._socket.sleep(seconds)

    def on_match_price(self, handler: Callable[[object], None]) -> None:
        """Register the callback for binary match-price events."""
        if not callable(handler):
            raise TypeError("Match-price handler must be callable")
        self._socket.on(MATCH_PRICE_EVENT, handler)

    def subscribe_match_price(self, symbols: tuple[str, ...]) -> None:
        """Subscribe connected clients to the requested match-price symbols."""
        if not self.connected:
            raise ConnectionError("Connect before subscribing to match prices")
        payload = build_symbol_subscription(symbols)
        logger.info(
            "Subscribing to Vietcap match-price stream",
            extra={"event": MATCH_PRICE_EVENT, "symbols": list(symbols)},
        )
        try:
            self._socket.emit(MATCH_PRICE_EVENT, payload)
        except Exception:
            logger.exception(
                "Failed to subscribe to Vietcap match-price stream",
                extra={"event": MATCH_PRICE_EVENT, "symbols": list(symbols)},
            )
            raise

    def _on_connect(self) -> None:
        logger.info("Socket.IO namespace connected")

    def _on_disconnect(self, reason: object | None = None) -> None:
        logger.info("Socket.IO namespace disconnected", extra={"reason": reason})

    def _on_connect_error(self, data: object) -> None:
        logger.error("Socket.IO connection error", extra={"error_data": data})

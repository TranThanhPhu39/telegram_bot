"""Connection lifecycle for the unofficial Vietcap Socket.IO endpoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
import logging
import os
from threading import Lock

import socketio

from data.vietcap.constants import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_RECONNECTION_ATTEMPTS,
    DEFAULT_RECONNECTION_DELAY_MAX_SECONDS,
    DEFAULT_RECONNECTION_DELAY_SECONDS,
    DEFAULT_RECONNECTION_ENABLED,
    DEFAULT_RECONNECTION_RANDOMIZATION_FACTOR,
    DEFAULT_RAW_DEBUG_EVENT_LIMIT,
    DEFAULT_SOCKET_PATH,
    DEFAULT_SOCKET_URL,
    BID_ASK_EVENT,
    INDEX_EVENT,
    MATCH_PRICE_EVENT,
    SOCKET_TRANSPORTS,
)
from data.vietcap.subscriptions import (
    build_index_subscription,
    build_symbol_subscription,
    normalize_index_symbols,
    normalize_symbols,
)

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
        raw_debug: bool = False,
        raw_debug_event_limit: int = DEFAULT_RAW_DEBUG_EVENT_LIMIT,
        socket_client: socketio.Client | None = None,
    ) -> None:
        if isinstance(raw_debug_event_limit, bool) or not isinstance(
            raw_debug_event_limit, int
        ):
            raise TypeError("raw_debug_event_limit must be an integer")
        if raw_debug_event_limit < 1:
            raise ValueError("raw_debug_event_limit must be at least 1")
        self.socket_url = socket_url or os.getenv(
            "VIETCAP_SOCKET_URL", DEFAULT_SOCKET_URL
        )
        self.socket_path = normalize_socketio_path(
            socket_path or os.getenv("VIETCAP_SOCKET_PATH", DEFAULT_SOCKET_PATH)
        )
        self._socket = socket_client or socketio.Client(
            reconnection=DEFAULT_RECONNECTION_ENABLED,
            reconnection_attempts=DEFAULT_RECONNECTION_ATTEMPTS,
            reconnection_delay=DEFAULT_RECONNECTION_DELAY_SECONDS,
            reconnection_delay_max=DEFAULT_RECONNECTION_DELAY_MAX_SECONDS,
            randomization_factor=DEFAULT_RECONNECTION_RANDOMIZATION_FACTOR,
            logger=engineio_logger,
            engineio_logger=engineio_logger,
        )
        self._match_price_subscription: frozenset[str] | None = None
        self._index_subscription: frozenset[str] | None = None
        self._bid_ask_subscription: frozenset[str] | None = None
        self._desired_match_price_symbols: tuple[str, ...] | None = None
        self._desired_index_symbols: tuple[str, ...] | None = None
        self._desired_bid_ask_symbols: tuple[str, ...] | None = None
        self._raw_debug = raw_debug
        self._raw_debug_event_limit = raw_debug_event_limit
        self._raw_debug_event_counts: dict[str, int] = {}
        self._raw_debug_lock = Lock()
        self._connection_generation = 0
        self._disconnect_count = 0
        self._lifecycle_lock = Lock()
        self._socket.on("connect", self._on_connect)
        self._socket.on("disconnect", self._on_disconnect)
        self._socket.on("connect_error", self._on_connect_error)

    @property
    def connected(self) -> bool:
        """Whether the default Socket.IO namespace is connected."""
        if self._socket.connected:
            return True
        namespaces = getattr(self._socket, "namespaces", None)
        return isinstance(namespaces, dict) and "/" in namespaces

    @property
    def connection_generation(self) -> int:
        """Number of successful namespace connections in this client lifetime."""
        with self._lifecycle_lock:
            return self._connection_generation

    @property
    def disconnect_count(self) -> int:
        """Number of observed namespace disconnect events."""
        with self._lifecycle_lock:
            return self._disconnect_count

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

    def interrupt_transport(self) -> None:
        """Close the active WebSocket without requesting a clean disconnect.

        This is intended for bounded resilience drills. The resulting transport
        error leaves Socket.IO responsible for reconnecting and restoring desired
        subscriptions.
        """
        if not self.connected:
            raise ConnectionError("Connect before interrupting the transport")
        if self._socket.transport() != "websocket":
            raise RuntimeError("Transport interruption requires WebSocket")

        engineio_client = getattr(self._socket, "eio", None)
        websocket = getattr(engineio_client, "ws", None)
        if websocket is None:
            raise RuntimeError("Active WebSocket transport is unavailable")

        logger.warning("Forcing Vietcap WebSocket transport interruption")
        websocket.close()

    def on_match_price(self, handler: Callable[[object], None]) -> None:
        """Register the callback for binary match-price events."""
        self._register_market_handler(MATCH_PRICE_EVENT, handler)

    def subscribe_match_price(self, symbols: tuple[str, ...]) -> None:
        """Subscribe connected clients to the requested match-price symbols."""
        if not self.connected:
            raise ConnectionError("Connect before subscribing to match prices")
        normalized_symbols = normalize_symbols(symbols)
        self._desired_match_price_symbols = normalized_symbols
        subscription = frozenset(normalized_symbols)
        if subscription == self._match_price_subscription:
            logger.info(
                "Skipping unchanged Vietcap match-price subscription",
                extra={
                    "event": MATCH_PRICE_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            return

        payload = build_symbol_subscription(normalized_symbols)
        logger.info(
            "Subscribing to Vietcap match-price stream",
            extra={
                "event": MATCH_PRICE_EVENT,
                "symbols": list(normalized_symbols),
            },
        )
        try:
            self._socket.emit(MATCH_PRICE_EVENT, payload)
        except Exception:
            logger.exception(
                "Failed to subscribe to Vietcap match-price stream",
                extra={
                    "event": MATCH_PRICE_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            raise
        self._match_price_subscription = subscription

    def on_index(self, handler: Callable[[object], None]) -> None:
        """Register the callback for binary index events."""
        self._register_market_handler(INDEX_EVENT, handler)

    def subscribe_index(self, symbols: tuple[str, ...]) -> None:
        """Subscribe connected clients to the requested index symbols."""
        if not self.connected:
            raise ConnectionError("Connect before subscribing to indices")
        normalized_symbols = normalize_index_symbols(symbols)
        self._desired_index_symbols = normalized_symbols
        subscription = frozenset(
            symbol.upper() for symbol in normalized_symbols
        )
        if subscription == self._index_subscription:
            logger.info(
                "Skipping unchanged Vietcap index subscription",
                extra={
                    "event": INDEX_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            return

        payload = build_index_subscription(normalized_symbols)
        logger.info(
            "Subscribing to Vietcap index stream",
            extra={"event": INDEX_EVENT, "symbols": list(normalized_symbols)},
        )
        try:
            self._socket.emit(INDEX_EVENT, payload)
        except Exception:
            logger.exception(
                "Failed to subscribe to Vietcap index stream",
                extra={
                    "event": INDEX_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            raise
        self._index_subscription = subscription

    def on_bid_ask(self, handler: Callable[[object], None]) -> None:
        """Register the callback for binary bid-ask events."""
        self._register_market_handler(BID_ASK_EVENT, handler)

    def subscribe_bid_ask(self, symbols: tuple[str, ...]) -> None:
        """Subscribe connected clients to the requested bid-ask symbols."""
        if not self.connected:
            raise ConnectionError("Connect before subscribing to bid-ask data")
        normalized_symbols = normalize_symbols(symbols)
        self._desired_bid_ask_symbols = normalized_symbols
        subscription = frozenset(normalized_symbols)
        if subscription == self._bid_ask_subscription:
            logger.info(
                "Skipping unchanged Vietcap bid-ask subscription",
                extra={
                    "event": BID_ASK_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            return

        payload = build_symbol_subscription(normalized_symbols)
        logger.info(
            "Subscribing to Vietcap bid-ask stream",
            extra={"event": BID_ASK_EVENT, "symbols": list(normalized_symbols)},
        )
        try:
            self._socket.emit(BID_ASK_EVENT, payload)
        except Exception:
            logger.exception(
                "Failed to subscribe to Vietcap bid-ask stream",
                extra={
                    "event": BID_ASK_EVENT,
                    "symbols": list(normalized_symbols),
                },
            )
            raise
        self._bid_ask_subscription = subscription

    def _on_connect(self) -> None:
        with self._lifecycle_lock:
            self._connection_generation += 1
        logger.info("Socket.IO namespace connected")
        self._restore_subscriptions()

    def _on_disconnect(self, reason: object | None = None) -> None:
        with self._lifecycle_lock:
            self._disconnect_count += 1
        self._match_price_subscription = None
        self._index_subscription = None
        self._bid_ask_subscription = None
        logger.info("Socket.IO namespace disconnected", extra={"reason": reason})

    def _on_connect_error(self, data: object) -> None:
        logger.error("Socket.IO connection error", extra={"error_data": data})

    def _register_market_handler(
        self,
        event: str,
        handler: Callable[[object], None],
    ) -> None:
        if not callable(handler):
            raise TypeError(f"{event} handler must be callable")
        if not self._raw_debug:
            self._socket.on(event, handler)
            return

        @wraps(handler)
        def debug_handler(payload: object) -> None:
            self._log_raw_event_metadata(event, payload)
            handler(payload)

        self._socket.on(event, debug_handler)

    def _log_raw_event_metadata(self, event: str, payload: object) -> None:
        with self._raw_debug_lock:
            event_number = self._raw_debug_event_counts.get(event, 0) + 1
            if event_number > self._raw_debug_event_limit:
                return
            self._raw_debug_event_counts[event] = event_number

        payload_size = (
            len(payload)
            if isinstance(payload, (bytes, bytearray, memoryview))
            else None
        )
        logger.debug(
            "Received raw Vietcap event metadata",
            extra={
                "event": event,
                "payload_type": type(payload).__name__,
                "payload_size": payload_size,
                "raw_debug_event_number": event_number,
                "raw_debug_event_limit": self._raw_debug_event_limit,
                "raw_debug_limit_reached": (
                    event_number == self._raw_debug_event_limit
                ),
            },
        )

    def _restore_subscriptions(self) -> None:
        self._restore_subscription(
            MATCH_PRICE_EVENT,
            self._desired_match_price_symbols,
            self.subscribe_match_price,
        )
        self._restore_subscription(
            INDEX_EVENT,
            self._desired_index_symbols,
            self.subscribe_index,
        )
        self._restore_subscription(
            BID_ASK_EVENT,
            self._desired_bid_ask_symbols,
            self.subscribe_bid_ask,
        )

    def _restore_subscription(
        self,
        event: str,
        symbols: tuple[str, ...] | None,
        subscriber: Callable[[tuple[str, ...]], None],
    ) -> None:
        if symbols is None:
            return
        try:
            subscriber(symbols)
        except Exception:
            logger.exception(
                "Failed to restore Vietcap subscription after reconnect",
                extra={"event": event, "symbols": list(symbols)},
            )

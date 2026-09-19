"""Unit tests for the connection-only Vietcap client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from data.vietcap.client import VietcapRealtimeClient, normalize_socketio_path


class FakeSocketClient:
    def __init__(self) -> None:
        self.connected = False
        self.sid = "test-sid"
        self.handlers: dict[str, Callable[..., None]] = {}
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []
        self.disconnect_calls = 0

    def on(self, event: str, handler: Callable[..., None]) -> None:
        self.handlers[event] = handler

    def connect(self, url: str, **kwargs: Any) -> None:
        self.connect_calls.append((url, kwargs))
        self.connected = True
        self.handlers["connect"]()

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False
        self.handlers["disconnect"]("client disconnect")

    def transport(self) -> str:
        return "websocket"

    def sleep(self, seconds: float) -> None:
        del seconds


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/ws/price/socket.io", "ws/price/socket.io"),
        ("ws/price/socket.io/", "ws/price/socket.io"),
        (" socket.io ", "socket.io"),
    ],
)
def test_normalize_socketio_path(raw: str, expected: str) -> None:
    assert normalize_socketio_path(raw) == expected


def test_normalize_socketio_path_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_socketio_path(" / ")


def test_connect_uses_websocket_only_and_custom_path() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    info = client.connect(timeout=7.5)

    assert info.sid == "test-sid"
    assert info.transport == "websocket"
    assert socket_client.connect_calls == [
        (
            "https://trading.vietcap.com.vn",
            {
                "socketio_path": "ws/price/socket.io",
                "transports": ["websocket"],
                "wait": True,
                "wait_timeout": 7.5,
            },
        )
    ]
    assert set(socket_client.handlers) == {
        "connect",
        "disconnect",
        "connect_error",
    }


def test_disconnect_is_idempotent() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.disconnect()
    client.connect()
    client.disconnect()
    client.disconnect()

    assert socket_client.disconnect_calls == 1

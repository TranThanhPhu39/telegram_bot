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
        self.emit_calls: list[tuple[str, object]] = []
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

    def emit(self, event: str, data: object) -> None:
        self.emit_calls.append((event, data))

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


def test_match_price_subscription_requires_connection() -> None:
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=FakeSocketClient()
    )

    with pytest.raises(ConnectionError, match="Connect before subscribing"):
        client.subscribe_match_price(("FPT",))


def test_register_and_subscribe_fpt_match_price() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    handler = lambda payload: None

    client.on_match_price(handler)
    client.connect()
    client.subscribe_match_price(("FPT",))

    assert socket_client.handlers["w-match-price"] is handler
    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT"]}')
    ]


def test_subscribe_fpt_acb_once_when_symbol_set_is_unchanged() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_match_price(("FPT", "ACB", "fpt"))
    client.subscribe_match_price(("acb", "fpt"))

    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT","ACB"]}')
    ]


def test_match_price_subscription_can_emit_again_after_disconnect() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.disconnect()
    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))

    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT","ACB"]}'),
        ("w-match-price", '{"symbols":["FPT","ACB"]}'),
    ]


def test_index_subscription_requires_connection() -> None:
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=FakeSocketClient()
    )

    with pytest.raises(ConnectionError, match="Connect before subscribing"):
        client.subscribe_index(("VNINDEX",))


def test_register_and_subscribe_vnindex_index_event() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    handler = lambda payload: None

    client.on_index(handler)
    client.connect()
    client.subscribe_index(("VNINDEX",))
    client.subscribe_index(("vnindex",))

    assert socket_client.handlers["index"] is handler
    assert socket_client.emit_calls == [("index", '{"symbols":["VNINDEX"]}')]


def test_index_subscription_can_emit_again_after_disconnect() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_index(("VNINDEX",))
    client.disconnect()
    client.connect()
    client.subscribe_index(("VNINDEX",))

    assert socket_client.emit_calls == [
        ("index", '{"symbols":["VNINDEX"]}'),
        ("index", '{"symbols":["VNINDEX"]}'),
    ]


def test_match_price_and_index_subscriptions_are_independent() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.subscribe_index(("VNINDEX",))

    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT","ACB"]}'),
        ("index", '{"symbols":["VNINDEX"]}'),
    ]


def test_bid_ask_subscription_requires_connection() -> None:
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=FakeSocketClient()
    )

    with pytest.raises(ConnectionError, match="Connect before subscribing"):
        client.subscribe_bid_ask(("FPT", "ACB"))


def test_register_and_subscribe_fpt_acb_bid_ask() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    handler = lambda payload: None

    client.on_bid_ask(handler)
    client.connect()
    client.subscribe_bid_ask(("fpt", "ACB"))
    client.subscribe_bid_ask(("acb", "FPT"))

    assert socket_client.handlers["w-bid-ask"] is handler
    assert socket_client.emit_calls == [
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}')
    ]


def test_bid_ask_subscription_can_emit_again_after_disconnect() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_bid_ask(("FPT", "ACB"))
    client.disconnect()
    client.connect()
    client.subscribe_bid_ask(("FPT", "ACB"))

    assert socket_client.emit_calls == [
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}'),
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}'),
    ]


def test_all_three_stream_subscriptions_are_independent() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.subscribe_index(("VNINDEX",))
    client.subscribe_bid_ask(("FPT", "ACB"))

    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT","ACB"]}'),
        ("index", '{"symbols":["VNINDEX"]}'),
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}'),
    ]
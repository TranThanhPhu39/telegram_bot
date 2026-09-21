"""Unit tests for the connection-only Vietcap client."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

import pytest

from data.vietcap.client import VietcapRealtimeClient, normalize_socketio_path


class FakeSocketClient:
    def __init__(self) -> None:
        self.connected = False
        self.sid = "test-sid"
        self.eio = FakeEngineIOClient()
        self.handlers: dict[str, Callable[..., None]] = {}
        self.on_calls: list[tuple[str, Callable[..., None]]] = []
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []
        self.emit_calls: list[tuple[str, object]] = []
        self.disconnect_calls = 0

    def on(self, event: str, handler: Callable[..., None]) -> None:
        self.on_calls.append((event, handler))
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


class FakeWebSocket:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeEngineIOClient:
    def __init__(self) -> None:
        self.ws = FakeWebSocket()


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


def test_default_socket_client_enables_reconnection(monkeypatch: pytest.MonkeyPatch) -> None:
    socket_client = FakeSocketClient()
    constructor_options: dict[str, object] = {}

    def create_socket_client(**kwargs: object) -> FakeSocketClient:
        constructor_options.update(kwargs)
        return socket_client

    monkeypatch.setattr("data.vietcap.client.socketio.Client", create_socket_client)

    VietcapRealtimeClient()

    assert constructor_options == {
        "reconnection": True,
        "reconnection_attempts": 0,
        "reconnection_delay": 1.0,
        "reconnection_delay_max": 30.0,
        "randomization_factor": 0.5,
        "logger": False,
        "engineio_logger": False,
    }


@pytest.mark.parametrize("invalid_limit", [0, -1])
def test_raw_debug_rejects_non_positive_event_limit(invalid_limit: int) -> None:
    with pytest.raises(ValueError, match="must be at least 1"):
        VietcapRealtimeClient(
            socket_client=FakeSocketClient(),  # type: ignore[arg-type]
            raw_debug_event_limit=invalid_limit,
        )


def test_raw_debug_rejects_non_integer_event_limit() -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        VietcapRealtimeClient(
            socket_client=FakeSocketClient(),  # type: ignore[arg-type]
            raw_debug_event_limit=True,
        )


def test_raw_debug_is_disabled_by_default(caplog: pytest.LogCaptureFixture) -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    received: list[object] = []
    client.on_match_price(received.append)

    with caplog.at_level(logging.DEBUG, logger="data.vietcap.client"):
        socket_client.handlers["w-match-price"](b"sensitive-payload")

    assert received == [b"sensitive-payload"]
    assert "Received raw Vietcap event metadata" not in caplog.text


def test_raw_debug_logs_bounded_metadata_without_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=socket_client,
        raw_debug=True,
        raw_debug_event_limit=2,
    )
    received: list[object] = []
    client.on_match_price(received.append)

    with caplog.at_level(logging.DEBUG, logger="data.vietcap.client"):
        for payload in (b"secret-one", b"secret-two", b"secret-three"):
            socket_client.handlers["w-match-price"](payload)

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Received raw Vietcap event metadata"
    ]
    assert received == [b"secret-one", b"secret-two", b"secret-three"]
    assert len(records) == 2
    assert [record.event for record in records] == [
        "w-match-price",
        "w-match-price",
    ]
    assert [record.payload_type for record in records] == ["bytes", "bytes"]
    assert [record.payload_size for record in records] == [10, 10]
    assert [record.raw_debug_event_number for record in records] == [1, 2]
    assert records[-1].raw_debug_limit_reached is True
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    ("register_method", "event"),
    [
        ("on_match_price", "w-match-price"),
        ("on_index", "index"),
        ("on_bid_ask", "w-bid-ask"),
    ],
)
def test_raw_debug_covers_each_market_stream(
    register_method: str,
    event: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=socket_client,
        raw_debug=True,
    )
    received: list[object] = []
    getattr(client, register_method)(received.append)

    with caplog.at_level(logging.DEBUG, logger="data.vietcap.client"):
        socket_client.handlers[event](memoryview(b"frame"))

    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Received raw Vietcap event metadata"
    )
    assert received == [memoryview(b"frame")]
    assert record.event == event
    assert record.payload_type == "memoryview"
    assert record.payload_size == 5


def test_disconnect_is_idempotent() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    client.disconnect()
    client.connect()
    client.disconnect()
    client.disconnect()

    assert socket_client.disconnect_calls == 1


def test_lifecycle_counters_track_connect_and_disconnect_events() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]

    assert client.connection_generation == 0
    assert client.disconnect_count == 0

    client.connect()
    client.disconnect()
    client.connect()

    assert client.connection_generation == 2
    assert client.disconnect_count == 1


def test_interrupt_transport_closes_websocket_without_clean_disconnect() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    client.connect()

    client.interrupt_transport()

    assert socket_client.eio.ws.close_calls == 1
    assert socket_client.disconnect_calls == 0


def test_interrupt_transport_requires_connection() -> None:
    client = VietcapRealtimeClient(  # type: ignore[arg-type]
        socket_client=FakeSocketClient()
    )

    with pytest.raises(ConnectionError, match="Connect before interrupting"):
        client.interrupt_transport()


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


def test_all_three_stream_subscriptions_restore_after_reconnect() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.subscribe_index(("VNINDEX",))
    client.subscribe_bid_ask(("FPT", "ACB"))
    socket_client.emit_calls.clear()

    socket_client.connected = False
    socket_client.handlers["disconnect"]("transport error")
    socket_client.connected = True
    socket_client.handlers["connect"]()

    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT","ACB"]}'),
        ("index", '{"symbols":["VNINDEX"]}'),
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}'),
    ]


def test_subscription_restores_during_socketio_connect_callback_ordering() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    client.connect()
    client.subscribe_match_price(("FPT",))
    socket_client.emit_calls.clear()

    socket_client.connected = False
    socket_client.handlers["disconnect"]("transport error")
    socket_client.namespaces = {"/": "reconnected-sid"}
    socket_client.handlers["connect"]()

    assert client.connected is True
    assert socket_client.emit_calls == [
        ("w-match-price", '{"symbols":["FPT"]}')
    ]


def test_subscription_restore_continues_after_one_stream_fails() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.subscribe_index(("VNINDEX",))
    client.subscribe_bid_ask(("FPT", "ACB"))
    socket_client.emit_calls.clear()
    original_emit = socket_client.emit

    def fail_match_price(event: str, data: object) -> None:
        if event == "w-match-price":
            raise RuntimeError("simulated emit failure")
        original_emit(event, data)

    socket_client.emit = fail_match_price  # type: ignore[method-assign]
    socket_client.connected = False
    socket_client.handlers["disconnect"]("transport error")
    socket_client.connected = True

    socket_client.handlers["connect"]()

    assert socket_client.emit_calls == [
        ("index", '{"symbols":["VNINDEX"]}'),
        ("w-bid-ask", '{"symbols":["FPT","ACB"]}'),
    ]


def test_repeated_reconnects_do_not_register_duplicate_listeners() -> None:
    socket_client = FakeSocketClient()
    client = VietcapRealtimeClient(socket_client=socket_client)  # type: ignore[arg-type]
    received = {"w-match-price": 0, "index": 0, "w-bid-ask": 0}

    def count(event: str) -> Callable[[object], None]:
        def handler(payload: object) -> None:
            del payload
            received[event] += 1

        return handler

    client.on_match_price(count("w-match-price"))
    client.on_index(count("index"))
    client.on_bid_ask(count("w-bid-ask"))
    client.connect()
    client.subscribe_match_price(("FPT", "ACB"))
    client.subscribe_index(("VNINDEX",))
    client.subscribe_bid_ask(("FPT", "ACB"))

    for _ in range(3):
        socket_client.connected = False
        socket_client.handlers["disconnect"]("transport error")
        socket_client.connected = True
        socket_client.handlers["connect"]()
        socket_client.handlers["w-match-price"](b"match-price")
        socket_client.handlers["index"](b"index")
        socket_client.handlers["w-bid-ask"](b"bid-ask")

    registered_events = [event for event, _handler in socket_client.on_calls]
    assert registered_events == [
        "connect",
        "disconnect",
        "connect_error",
        "w-match-price",
        "index",
        "w-bid-ask",
    ]
    assert received == {"w-match-price": 3, "index": 3, "w-bid-ask": 3}

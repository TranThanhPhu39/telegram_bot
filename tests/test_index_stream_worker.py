"""Tests for the background realtime VNINDEX breadth/liquidity worker."""

from __future__ import annotations

import threading
import time

import pytest

from data.market_state import LatestIndexState
from data.vietcap.proto import price_pb2
from runtime.index_stream_worker import (
    IndexStreamWorker,
    start_index_stream_worker_from_env,
)


def raw_index_payload() -> bytes:
    """Serialized wire payload matching the real Vietcap index event shape."""
    return price_pb2.IndexMessage(
        code="VNINDEX", symbol="VNINDEX", price=1_280.5, change=5.25,
        changePercent=0.41, totalShares=500_000_000, totalValue=12_500_000_000_000,
        totalStockIncrease=250, totalStockDecline=120, totalStockNoChange=60,
        totalStockCeiling=8, totalStockFloor=3, time="11:05:22",
    ).SerializeToString()


class FakeRealtimeClient:
    """Connects immediately and emits one index snapshot, then stays 'connected'."""

    def __init__(self, *, fail_connect: bool = False) -> None:
        self.fail_connect = fail_connect
        self.connected = False
        self.disconnected = False
        self._handler = None
        self.subscribed: tuple[str, ...] | None = None

    def on_index(self, handler) -> None:
        self._handler = handler

    def connect(self, timeout: float = 10.0):
        if self.fail_connect:
            raise ConnectionError("simulated connect failure")
        self.connected = True

    def subscribe_index(self, symbols: tuple[str, ...]) -> None:
        self.subscribed = symbols
        if self._handler is not None:
            self._handler(raw_index_payload())

    def sleep(self, seconds: float) -> None:
        time.sleep(min(seconds, 0.01))

    def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True


def test_worker_populates_index_state_from_first_connect() -> None:
    state = LatestIndexState()
    client = FakeRealtimeClient()
    worker = IndexStreamWorker(
        state, client_factory=lambda: client, poll_interval_seconds=0.01,
    )
    worker.start()
    try:
        deadline = time.monotonic() + 2.0
        while state.get("VNINDEX") is None and time.monotonic() < deadline:
            time.sleep(0.01)
        cached = state.get("VNINDEX")
        assert cached is not None
        assert cached.advances == 250.0
        assert client.subscribed == ("VNINDEX",)
    finally:
        worker.stop(timeout=2.0)
    assert client.disconnected is True
    assert worker.running is False


def test_worker_retries_after_a_failed_initial_connect() -> None:
    state = LatestIndexState()
    attempts: list[FakeRealtimeClient] = []

    def factory() -> FakeRealtimeClient:
        client = FakeRealtimeClient(fail_connect=len(attempts) == 0)
        attempts.append(client)
        return client

    worker = IndexStreamWorker(
        state, client_factory=factory,
        reconnect_delay_seconds=0.01, max_reconnect_delay_seconds=0.02,
        poll_interval_seconds=0.01,
    )
    worker.start()
    try:
        deadline = time.monotonic() + 2.0
        while state.get("VNINDEX") is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert state.get("VNINDEX") is not None
    finally:
        worker.stop(timeout=2.0)
    assert worker.connect_failures >= 1
    assert len(attempts) >= 2


def test_worker_never_busy_loops_when_connect_keeps_failing() -> None:
    """Bounded retry: the thread must sleep between attempts, not spin."""
    state = LatestIndexState()

    def factory() -> FakeRealtimeClient:
        return FakeRealtimeClient(fail_connect=True)

    worker = IndexStreamWorker(
        state, client_factory=factory,
        reconnect_delay_seconds=0.05, max_reconnect_delay_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    worker.start()
    try:
        time.sleep(0.3)
    finally:
        worker.stop(timeout=2.0)
    # With a 0.05s floor delay, 0.3s should yield only a handful of attempts.
    assert worker.connect_attempts <= 10
    assert state.get("VNINDEX") is None


def test_stop_before_start_is_a_no_op() -> None:
    state = LatestIndexState()
    worker = IndexStreamWorker(state, client_factory=FakeRealtimeClient)
    worker.stop(timeout=1.0)  # must not raise
    assert worker.running is False


def test_start_index_stream_worker_from_env_disabled_returns_none() -> None:
    state = LatestIndexState()
    worker = start_index_stream_worker_from_env(
        state, environ={"INDEX_STREAM_WORKER_ENABLED": "false"},
    )
    assert worker is None


def test_start_index_stream_worker_from_env_rejects_non_index_state() -> None:
    with pytest.raises(TypeError):
        IndexStreamWorker(object())  # type: ignore[arg-type]

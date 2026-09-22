"""Background realtime VNINDEX breadth/liquidity feed.

Wraps ``VietcapRealtimeClient`` + ``IndexStatePipeline`` (previously only
exercised standalone by ``scripts/test_realtime_index.py``) in a bounded
daemon-thread worker so production can keep a shared ``LatestIndexState``
warm without ever blocking the Telegram polling loop.

``/market`` and ``/soi`` both read this same state (see
``RuntimeBotDataService._index_breadth_liquidity``); when the feed is down
or hasn't produced a VNINDEX snapshot yet they simply see an empty state and
report breadth/liquidity as unavailable rather than fabricating anything.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import os
import threading

from data.market_state import LatestIndexState
from data.vietcap.client import VietcapRealtimeClient
from data.vietcap.constants import VNINDEX_SYMBOL
from data.vietcap.pipeline import IndexStatePipeline

LOGGER = logging.getLogger(__name__)

DEFAULT_SYMBOLS: tuple[str, ...] = (VNINDEX_SYMBOL,)
DEFAULT_RECONNECT_DELAY_SECONDS = 5.0
DEFAULT_MAX_RECONNECT_DELAY_SECONDS = 60.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0


class IndexStreamWorker:
    """Daemon thread keeping ``index_state`` updated from the Vietcap index socket.

    Reconnection within one connected session is handled by
    ``VietcapRealtimeClient``'s own bounded Socket.IO reconnection policy. This
    worker adds the outer retry loop for the case where the *initial* connect
    fails (or the client gives up reconnecting entirely): it backs off between
    attempts, capped at ``max_reconnect_delay_seconds``, and never busy-loops.
    """

    def __init__(
        self,
        index_state: LatestIndexState,
        *,
        symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
        client_factory: Callable[[], VietcapRealtimeClient] | None = None,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        reconnect_delay_seconds: float = DEFAULT_RECONNECT_DELAY_SECONDS,
        max_reconnect_delay_seconds: float = DEFAULT_MAX_RECONNECT_DELAY_SECONDS,
    ) -> None:
        if not isinstance(index_state, LatestIndexState):
            raise TypeError("index_state must be a LatestIndexState")
        if not symbols:
            raise ValueError("symbols must not be empty")
        self._index_state = index_state
        self._symbols = symbols
        self._client_factory = client_factory or VietcapRealtimeClient
        self._connect_timeout_seconds = connect_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._max_reconnect_delay_seconds = max_reconnect_delay_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._client: VietcapRealtimeClient | None = None
        self.connect_attempts = 0
        self.connect_failures = 0

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> threading.Thread:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("index stream worker has been stopped")
            if self._thread is not None:
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="index-stream", daemon=True
            )
            self._thread.start()
            return self._thread

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
            client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                LOGGER.exception("Error disconnecting Vietcap realtime client")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self) -> None:
        delay = self._reconnect_delay_seconds
        while not self._stop.is_set():
            self.connect_attempts += 1
            try:
                self._connect_and_hold()
                delay = self._reconnect_delay_seconds
            except Exception:
                self.connect_failures += 1
                LOGGER.exception(
                    "Vietcap realtime index connection failed; retrying in %.0fs",
                    delay,
                )
            finally:
                with self._lock:
                    self._client = None
            if self._stop.is_set():
                return
            self._stop.wait(delay)
            delay = min(delay * 2, self._max_reconnect_delay_seconds)

    def _connect_and_hold(self) -> None:
        client = self._client_factory()
        pipeline = IndexStatePipeline(self._index_state, self._symbols)
        client.on_index(pipeline.handle)
        with self._lock:
            self._client = client
        client.connect(timeout=self._connect_timeout_seconds)
        client.subscribe_index(self._symbols)
        LOGGER.info(
            "Vietcap realtime index stream connected symbols=%s", self._symbols
        )
        try:
            while not self._stop.is_set() and client.connected:
                client.sleep(self._poll_interval_seconds)
        finally:
            try:
                client.disconnect()
            except Exception:
                LOGGER.exception("Error disconnecting Vietcap realtime client")


def _flag(raw: str | None, default: bool) -> bool:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def start_index_stream_worker_from_env(
    index_state: LatestIndexState,
    *,
    environ: Mapping[str, str] | None = None,
) -> IndexStreamWorker | None:
    """Start the background realtime VNINDEX breadth/liquidity worker.

    Never blocks the Telegram polling loop: connecting and receiving happen
    on their own daemon thread. Returns ``None`` when explicitly disabled via
    ``INDEX_STREAM_WORKER_ENABLED=false`` (for example in offline/dev runs
    without network access to the Vietcap socket).
    """
    source = os.environ if environ is None else environ
    if not _flag(source.get("INDEX_STREAM_WORKER_ENABLED"), True):
        LOGGER.info(
            "Realtime index stream worker disabled (INDEX_STREAM_WORKER_ENABLED=false)"
        )
        return None

    worker = IndexStreamWorker(index_state)
    worker.start()
    LOGGER.info("Realtime index stream worker started")
    return worker

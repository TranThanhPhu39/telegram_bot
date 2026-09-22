"""Tests for the Issue 5 on-demand, per-ticker targeted news refresh worker."""

from datetime import datetime, timezone
import sqlite3
import threading

import pytest

from intelligence.news.models import NewsItem
from intelligence.news.pipeline import CafeFCompanyCatalogProvider
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import LexiconSentimentModel
from runtime.news_refresh import TargetedNewsRefreshWorker, TargetedNewsRefreshResult

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def _symbols_connection(symbols: tuple[str, ...]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE symbols(symbol TEXT PRIMARY KEY,instrument_type TEXT,is_active INTEGER)"
    )
    connection.executemany(
        "INSERT INTO symbols VALUES(?,?,?)",
        [(symbol, "STOCK", 1) for symbol in symbols],
    )
    return connection


def _offline_catalog() -> CafeFCompanyCatalogProvider:
    """No live CafeF catalog access in this sandbox; the linker already
    falls back to the SQLite universe on failure (see
    intelligence/news/pipeline.py::build_ticker_linker)."""
    return CafeFCompanyCatalogProvider(
        request_get=lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    )


class FakeProvider:
    def __init__(self, items: tuple[NewsItem, ...] = ()):
        self.items = items
        self.calls: list[int] = []

    def fetch(self, limit: int) -> tuple[NewsItem, ...]:
        self.calls.append(limit)
        return self.items


def _worker(
    *,
    symbols=("HC1", "FPT"),
    provider_items=(),
    fetch_limit=60,
    cooldown_seconds=3600.0,
    monotonic=None,
    tmp_path=None,
    sentiment_factory=None,
):
    db_path = (tmp_path / "news.db") if tmp_path else ":memory:"
    if sentiment_factory is None:
        def sentiment_factory():
            return LexiconSentimentModel(now=lambda: NOW)

    kwargs = dict(
        connection_factory=lambda: _symbols_connection(symbols),
        repository_factory=lambda: SQLiteNewsRepository(db_path),
        provider_factory=lambda: FakeProvider(provider_items),
        catalog_factory=_offline_catalog,
        sentiment_factory=sentiment_factory,
        fetch_limit=fetch_limit,
        cooldown_seconds=cooldown_seconds,
    )
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    return TargetedNewsRefreshWorker(**kwargs)


def test_rejects_invalid_fetch_limit_and_cooldown() -> None:
    with pytest.raises(ValueError):
        _worker(fetch_limit=0)
    with pytest.raises(ValueError):
        _worker(cooldown_seconds=-1)


def test_stop_before_start_is_a_no_op() -> None:
    worker = _worker()
    worker.stop(1)  # must not raise
    assert worker.request("HC1") is False


def test_request_after_stop_is_rejected() -> None:
    worker = _worker()
    worker.start()
    worker.stop(2)
    assert worker.request("HC1") is False


def test_request_normalizes_and_rejects_blank_symbol() -> None:
    worker = _worker(cooldown_seconds=3600.0)
    assert worker.request("   ") is False
    assert worker.request("") is False


def test_worker_deduplicates_inflight_and_cooldown_requests() -> None:
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    class BlockingProvider:
        def fetch(self, limit):
            started.set()
            assert release.wait(2)
            completed.set()
            return ()

    worker = TargetedNewsRefreshWorker(
        connection_factory=lambda: _symbols_connection(("HC1",)),
        repository_factory=lambda: SQLiteNewsRepository(":memory:"),
        provider_factory=BlockingProvider,
        catalog_factory=_offline_catalog,
        sentiment_factory=lambda: LexiconSentimentModel(now=lambda: NOW),
        cooldown_seconds=3600.0,
    )
    worker.start()
    try:
        assert worker.request(" hc1 ") is True
        assert started.wait(2)
        # Duplicate in-flight request for the same (normalized) symbol.
        assert worker.request("HC1") is False
        release.set()
        assert completed.wait(2)
        # Now within the cooldown window for the same symbol.
        assert worker.request("HC1") is False
    finally:
        release.set()
        worker.stop(2)


def test_worker_refreshes_symbol_and_persists_via_existing_pipeline(tmp_path) -> None:
    item = NewsItem(
        "hc1-1", "cafef_rss", "https://cafef.vn/hc1-bai-viet.chn", NOW,
        "HC1 công bố kết quả kinh doanh quý",
    )
    completed = threading.Event()
    published: list[TargetedNewsRefreshResult] = []

    worker = _worker(
        symbols=("HC1", "FPT"), provider_items=(item,), tmp_path=tmp_path,
    )

    def listener(result: TargetedNewsRefreshResult) -> None:
        published.append(result)
        completed.set()

    worker.add_listener(listener)
    worker.start()
    try:
        assert worker.request("HC1") is True
        assert completed.wait(2)
        assert len(published) == 1
        assert published[0].symbol == "HC1"
        assert published[0].inserted == 1
        assert published[0].articles_found == 1

        repository = SQLiteNewsRepository(tmp_path / "news.db")
        stored = repository.latest_for_ticker("HC1", 5)
        assert len(stored) == 1
        assert stored[0].id == "hc1-1"
    finally:
        worker.stop(2)
        worker.close()


def test_worker_passes_configured_fetch_limit_to_provider(tmp_path) -> None:
    provider_holder: list[FakeProvider] = []
    completed = threading.Event()

    def provider_factory():
        provider = FakeProvider(())
        provider_holder.append(provider)
        return provider

    worker = TargetedNewsRefreshWorker(
        connection_factory=lambda: _symbols_connection(("HC1",)),
        repository_factory=lambda: SQLiteNewsRepository(tmp_path / "news.db"),
        provider_factory=provider_factory,
        catalog_factory=_offline_catalog,
        sentiment_factory=lambda: LexiconSentimentModel(now=lambda: NOW),
        fetch_limit=77,
        cooldown_seconds=3600.0,
    )
    worker.add_listener(lambda _result: completed.set())
    worker.start()
    try:
        assert worker.request("HC1") is True
        assert completed.wait(2)
        assert provider_holder and provider_holder[0].calls == [77]
    finally:
        worker.stop(2)


def test_worker_builds_sentiment_model_at_most_once(tmp_path) -> None:
    """The sentiment factory is only ever invoked lazily on first use and
    reused afterwards -- mirrors NewsRefreshRunner's "PhoBERT loaded at most
    once" contract, now shared with this second, independently threaded
    runner via intelligence.news.sentiment.get_shared_sentiment_model()."""
    builds: list[int] = []
    first_done = threading.Event()
    second_done = threading.Event()
    calls = {"count": 0}

    def sentiment_factory():
        builds.append(1)
        return LexiconSentimentModel(now=lambda: NOW)

    def listener(_result):
        calls["count"] += 1
        if calls["count"] == 1:
            first_done.set()
        else:
            second_done.set()

    worker = _worker(
        symbols=("HC1", "FPT"), tmp_path=tmp_path, sentiment_factory=sentiment_factory,
    )
    worker.add_listener(listener)
    worker.start()
    try:
        assert worker.request("HC1") is True
        assert first_done.wait(2)
        assert worker.request("FPT") is True
        assert second_done.wait(2)
        assert len(builds) == 1
    finally:
        worker.stop(2)

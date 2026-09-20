"""Tests for independent sector-member history synchronization."""

from datetime import date
import threading
import time

from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from data.database import connect_database
from runtime.bot_service import RuntimeBotDataService
from runtime.sector_history_sync import SectorHistorySynchronizer, SectorHistorySyncWorker
from scanner.universe import ScannerInstrument


def payload(symbol: str, count: int = 260) -> dict[str, object]:
    timestamps = [1_789_300_800 + index * 86_400 for index in range(count)]
    closes = [100.0 + index for index in range(count)]
    return {
        "symbol": symbol, "t": [str(value) for value in timestamps],
        "o": closes, "h": [value + 1 for value in closes],
        "l": [value - 1 for value in closes], "c": closes,
        "v": [100_000.0 + index for index in range(count)],
    }


class RetryClient:
    def __init__(self, failures: dict[str, int] | None = None):
        self.failures = dict(failures or {})
        self.calls: list[str] = []

    def get_gap_chart(self, symbols, **kwargs):
        symbol = symbols[0]
        self.calls.append(symbol)
        remaining = self.failures.get(symbol, 0)
        if remaining:
            self.failures[symbol] = remaining - 1
            raise ValueError("temporary timeout")
        return [payload(symbol)]


def synchronizer(client, *, sleep=lambda _: None):
    connection = connect_database("sqlite:///:memory:")
    service = SectorHistorySynchronizer(
        client, connection, retry_attempts=3, retry_base_seconds=1,
        now=lambda: 1_800_000_000, sleep=sleep,
    )
    members = ("ACB", "AAA", "BBB", "CCC", "DDD")
    upsert_sector_memberships(connection, [
        SectorMembership(symbol, "BANK", "Banks", date(2020, 1, 1), None, "TEST")
        for symbol in members
    ])
    return service


def test_sync_retries_with_backoff_and_persists_each_member() -> None:
    delays: list[float] = []
    client = RetryClient({"AAA": 2})
    service = synchronizer(client, sleep=delays.append)

    result = service.sync_symbol_sector("ACB")

    assert result.downloaded == 5
    assert result.cached == 0
    assert result.failed == ()
    assert client.calls.count("AAA") == 3
    assert delays == [1, 2]
    assert service._cached_bar_count("AAA") == 260


def test_sync_keeps_successes_and_only_retries_failed_member_next_run() -> None:
    client = RetryClient({"DDD": 6})
    service = synchronizer(client)

    first = service.sync_symbol_sector("ACB")
    second = service.sync_symbol_sector("ACB")

    assert first.downloaded == 4
    assert first.failed == ("DDD",)
    assert second.cached == 4
    assert second.failed == ("DDD",)
    assert client.calls.count("ACB") == 1
    assert client.calls.count("DDD") == 6


def test_sync_can_bound_each_batch_without_losing_total_progress() -> None:
    client = RetryClient()
    service = synchronizer(client)

    first = service.sync_symbol_sector("ACB", max_uncached_members=2)
    second = service.sync_symbol_sector("ACB", max_uncached_members=2)

    assert first.members == 5
    assert first.downloaded == 2
    assert first.cached == 0
    assert second.downloaded == 2
    assert second.cached == 2
    assert len(set(client.calls)) == 4


def test_worker_accepts_arbitrary_symbol_and_deduplicates_inflight_and_cooldown() -> None:
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    class BlockingSynchronizer:
        def __init__(self):
            self.calls: list[str] = []

        def sync_symbol_sector(self, symbol: str, **kwargs):
            self.calls.append(symbol)
            if symbol == "VHM":
                started.set()
                assert release.wait(2)
                completed.set()

    fake = BlockingSynchronizer()
    worker = SectorHistorySyncWorker(
        (), interval_seconds=3600, request_cooldown_seconds=3600,
        synchronizer_factory=lambda: fake,
    )
    worker.start()
    try:
        assert worker.request(" vhm ") is True
        assert started.wait(2)
        assert worker.request("VHM") is False
        release.set()
        assert completed.wait(2)
        assert worker.request("VHM") is False
        assert fake.calls == ["VHM"]
    finally:
        release.set()
        worker.stop(2)


def test_arbitrary_symbol_request_populates_sector_and_clears_structural_missing(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'dynamic-sector.db'}"
    runtime_connection = connect_database(database_url)
    runtime = RuntimeBotDataService(
        RetryClient(), runtime_connection,
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
    )
    members = ("VHM", "AAA", "BBB", "CCC", "DDD", "EEE")
    upsert_sector_memberships(runtime_connection, [
        SectorMembership(
            symbol, "REAL_ESTATE", "Real Estate",
            date(2020, 1, 1), None, "TEST",
        )
        for symbol in members
    ])
    def build_worker_synchronizer():
        connection = connect_database(database_url)
        return SectorHistorySynchronizer(
            RetryClient(), connection, now=lambda: 1_800_000_000,
            sleep=lambda _: None,
        )

    worker = SectorHistorySyncWorker(
        (), interval_seconds=3600, request_cooldown_seconds=3600,
        max_members_per_run=8,
        synchronizer_factory=build_worker_synchronizer,
    )
    worker.start()
    runtime.set_sector_history_requester(worker.request)
    try:
        first = runtime.symbol_overview("VHM", "ASMF")
        assert "Đã xếp VHM vào hàng đợi đồng bộ nền." in first

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            ready = runtime_connection.execute(
                "SELECT COUNT(*) FROM sector_memberships sm "
                "WHERE sm.sector_code='REAL_ESTATE' AND "
                "(SELECT COUNT(*) FROM candles c WHERE c.symbol=sm.symbol "
                "AND c.timeframe='ONE_DAY') >= 126"
            ).fetchone()[0]
            if ready >= 5:
                break
            time.sleep(0.01)
        assert ready >= 5

        second = runtime.symbol_overview("VHM", "ASMF")
        assert "Sector=MISSING" not in second
        assert "sức mạnh ngành/breadth" not in second
    finally:
        worker.stop(2)
        runtime_connection.close()

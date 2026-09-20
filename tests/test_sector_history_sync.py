"""Tests for independent sector-member history synchronization."""

from datetime import date

from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from data.database import connect_database
from runtime.sector_history_sync import SectorHistorySynchronizer


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

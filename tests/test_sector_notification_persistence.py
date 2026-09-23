"""Sector-sync notification state survives a bot restart without spamming."""

from __future__ import annotations

import asyncio

import pytest

from data.database import connect_database
from data.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS, bootstrap_schema
from runtime.sector_history_sync import SectorSyncResult
from telegram_bot.sector_notification_store import SQLiteNotificationStore
from telegram_bot.sector_notifications import (
    SectorSyncNotificationBroker,
    deliver_sector_notifications,
)


def result(
    *, usable: int, failed=(), sector: str | None = "8600", symbol: str = "VHM"
) -> SectorSyncResult:
    return SectorSyncResult(symbol, sector, 123, 0, usable, tuple(failed))


class FakeBot:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        if self.always_fail:
            raise RuntimeError("permanent Telegram failure")
        self.sent.append(kwargs)


@pytest.fixture()
def database_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'bot.sqlite3').as_posix()}"


def restart(database_url: str, **kwargs) -> SectorSyncNotificationBroker:
    """Build a broker exactly as a fresh bot process would."""
    return SectorSyncNotificationBroker(
        SQLiteNotificationStore(lambda: connect_database(database_url)), **kwargs
    )


def test_registration_survives_service_recreation(database_url) -> None:
    restart(database_url).watch(77, "vhm")

    assert restart(database_url).is_watching(77, "VHM")


def test_incomplete_state_and_pending_delivery_survive_restart(database_url) -> None:
    first = restart(database_url)
    first.watch(77, "VHM")
    assert first.publish(result(usable=2, failed=("AAA",))) == 1

    # The process dies before the dispatcher delivers anything.
    recovered = restart(database_url)
    pending = recovered.drain()
    assert len(pending) == 1
    assert pending[0].chat_id == 77 and not pending[0].ready
    assert "2/123" in pending[0].text

    recovered.mark_delivered(pending[0])
    assert restart(database_url).drain() == ()
    # The single-incomplete rule is still honoured after the restart.
    assert restart(database_url).publish(result(usable=3, failed=("BBB",))) == 0


def test_ready_is_delivered_after_incomplete_and_never_repeats(database_url) -> None:
    broker = restart(database_url)
    broker.watch(77, "VHM")
    broker.publish(result(usable=2, failed=("AAA",)))
    broker.mark_delivered(broker.drain()[0])

    assert restart(database_url).publish(result(usable=5)) == 1
    after_ready = restart(database_url)
    ready = after_ready.drain()
    assert len(ready) == 1 and ready[0].ready
    after_ready.mark_delivered(ready[0])

    final = restart(database_url)
    assert final.drain() == ()
    assert final.publish(result(usable=5)) == 0
    assert not final.is_watching(77, "VHM")


def test_failed_delivery_remains_retryable_then_stops_at_the_attempt_budget(
    database_url,
) -> None:
    broker = restart(database_url, max_delivery_attempts=3)
    broker.watch(77, "VHM")
    broker.publish(result(usable=5))
    bot = FakeBot(always_fail=True)

    for _ in range(2):
        with pytest.raises(RuntimeError, match="permanent"):
            asyncio.run(deliver_sector_notifications(bot, broker))
        assert broker.pending_count() == 1  # still retryable, not delivered

    with pytest.raises(RuntimeError, match="permanent"):
        asyncio.run(deliver_sector_notifications(bot, broker))
    assert broker.pending_count() == 0  # attempt budget exhausted
    assert bot.sent == []


def test_multiple_chats_for_one_symbol_stay_independent(database_url) -> None:
    broker = restart(database_url)
    broker.watch(1, "VHM")
    broker.watch(2, "VHM")
    assert broker.publish(result(usable=2, failed=("AAA",))) == 2

    queued = broker.drain()
    broker.mark_delivered(queued[0])

    survivor = restart(database_url).drain()
    assert len(survivor) == 1
    assert survivor[0].chat_id == queued[1].chat_id


def test_duplicate_worker_result_is_deduplicated(database_url) -> None:
    broker = restart(database_url)
    broker.watch(77, "VHM")
    identical = result(usable=5)

    assert broker.publish(identical) == 1
    assert broker.publish(identical) == 0
    assert len(broker.drain()) == 1


def test_late_registration_sees_retained_incomplete_result_after_restart(
    database_url,
) -> None:
    assert restart(database_url).publish(result(usable=2, failed=("AAA",))) == 0

    late = restart(database_url)
    late.watch(77, "VHM")
    pending = late.drain()
    assert len(pending) == 1 and "2/123" in pending[0].text
    assert late.is_watching(77, "VHM")


def test_already_ready_sector_leaves_no_orphan_registration(database_url) -> None:
    broker = restart(database_url)
    broker.watch(77, "VHM")
    broker.unwatch(77, "VHM")  # runtime reported that no sync is needed

    assert not broker.is_watching(77, "VHM")
    assert restart(database_url).drain() == ()


def test_unwatch_still_delivers_an_already_queued_notification(database_url) -> None:
    broker = restart(database_url)
    broker.watch(77, "VHM")
    broker.publish(result(usable=2, failed=("AAA",)))

    broker.unwatch(77, "VHM")

    assert not broker.is_watching(77, "VHM")
    assert len(restart(database_url).drain()) == 1


def test_stale_registration_cleanup_is_configurable(database_url) -> None:
    clock = [1_000.0]
    broker = restart(
        database_url, registration_ttl_seconds=100.0, now=lambda: clock[0]
    )
    broker.watch(77, "VHM")

    clock[0] = 1_500.0
    assert broker.purge_stale() == 1
    assert not restart(database_url).is_watching(77, "VHM")


def test_unknown_sector_closes_the_registration_with_one_notice(database_url) -> None:
    broker = restart(database_url)
    broker.watch(77, "VHM")

    assert broker.publish(result(usable=0, sector=None)) == 1
    pending = broker.drain()
    assert "chưa có phân loại ngành" in pending[0].text
    assert not broker.is_watching(77, "VHM")


def test_migration_six_preserves_existing_database_contents(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}"
    connection = connect_database(database_url)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
            "applied_at INTEGER NOT NULL DEFAULT (unixepoch()))"
        )
        for migration in MIGRATIONS[:5]:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        connection.execute("INSERT INTO symbols (symbol) VALUES ('ACB')")
        connection.execute(
            "INSERT INTO users (telegram_user_id, default_risk_per_trade_pct) "
            "VALUES (42, 1.5)"
        )
        connection.commit()
    finally:
        connection.close()

    connection = connect_database(database_url)
    try:
        assert bootstrap_schema(connection) == LATEST_SCHEMA_VERSION
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"sector_sync_watchers", "sector_sync_results"} <= tables
        assert connection.execute(
            "SELECT symbol FROM symbols"
        ).fetchone()["symbol"] == "ACB"
        assert connection.execute(
            "SELECT default_risk_per_trade_pct FROM users"
        ).fetchone()[0] == 1.5
        assert [
            (row["version"], row["name"]) for row in connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            )
        ][:5] == [
            (1, "initial_v1_schema"), (2, "asmf_eod_inputs"),
            (3, "asmf_bank_financials"), (4, "portfolio_watchlist_holdings"),
            (5, "portfolio_exact_decimals"),
        ]
    finally:
        connection.close()


def test_startup_restores_pending_work_and_shutdown_stays_bounded(database_url) -> None:
    seed = restart(database_url)
    seed.watch(77, "VHM")
    seed.publish(result(usable=5))

    started = restart(database_url)
    bot = FakeBot()
    assert asyncio.run(deliver_sector_notifications(bot, started)) == 1
    assert bot.sent[0]["chat_id"] == 77

    # A second process start has no outstanding work and returns immediately.
    assert asyncio.run(deliver_sector_notifications(FakeBot(), restart(database_url))) == 0

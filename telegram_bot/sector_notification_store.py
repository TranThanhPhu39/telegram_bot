"""Durable state for sector-sync completion notifications.

This module is deliberately free of Telegram and provider imports.  It owns
only the notification bookkeeping that must survive a bot restart:

* which chat is still waiting for which symbol;
* whether that chat already received its single INCOMPLETE notice;
* a notification that has been queued but not yet delivered;
* the latest worker result retained per symbol for late subscribers.

Two interchangeable stores are provided.  ``InMemoryNotificationStore`` keeps
the pre-existing RAM-only behaviour (used by tests and by any caller that does
not supply a database).  ``SQLiteNotificationStore`` persists the same state in
the main runtime SQLite database through the existing migration framework, so
no second data pipeline or database is introduced.

Concurrency: a single bot process owns these tables.  The broker serialises
every operation with one process-level lock, and each store write runs in its
own SQLite transaction, so reads and writes stay consistent without holding a
cross-thread connection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import sqlite3

PENDING_INCOMPLETE = "INCOMPLETE"
PENDING_READY = "READY"
PENDING_UNAVAILABLE = "UNAVAILABLE"
PENDING_KINDS = (PENDING_INCOMPLETE, PENDING_READY, PENDING_UNAVAILABLE)

#: Usable peer histories required before a sector counts as READY.  This mirrors
#: ``runtime.bot_service`` and is duplicated here only to keep this module free
#: of runtime imports; both values must stay in step.
READY_MEMBER_THRESHOLD = 5


def canonical_chat_id(chat_id: int | str) -> str:
    """Return the canonical text key for a Telegram chat identifier."""
    text = str(chat_id).strip()
    if not text:
        raise ValueError("chat_id must not be empty")
    return text


def decode_chat_id(text: str) -> int | str:
    """Restore the original chat identifier type from its canonical key."""
    candidate = text.strip()
    if candidate.lstrip("-").isdigit():
        try:
            return int(candidate)
        except ValueError:  # pragma: no cover - defensive
            return candidate
    return candidate


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not normalized or not normalized.isalnum() or not normalized.isascii():
        raise ValueError("invalid stock symbol")
    return normalized


@dataclass(frozen=True, slots=True)
class RetainedResult:
    """The notification-relevant projection of one worker sync pass."""

    requested_symbol: str
    sector_code: str | None
    members: int
    usable: int
    failed_count: int

    @property
    def ready(self) -> bool:
        return self.usable >= READY_MEMBER_THRESHOLD

    @property
    def terminal(self) -> bool:
        return self.ready or self.sector_code is None

    @property
    def fingerprint(self) -> str:
        return "|".join((
            self.sector_code or "-",
            str(self.members),
            str(self.usable),
            str(self.failed_count),
        ))

    @classmethod
    def from_sync_result(cls, result) -> "RetainedResult":
        """Project a ``SectorSyncResult`` without importing the runtime module."""
        return cls(
            requested_symbol=normalize_symbol(result.requested_symbol),
            sector_code=result.sector_code,
            members=int(result.members),
            usable=int(result.usable),
            failed_count=len(tuple(result.failed)),
        )


@dataclass(frozen=True, slots=True)
class WatcherState:
    """One chat waiting for one symbol."""

    chat_id: str
    symbol: str
    incomplete_sent: bool = False
    closed: bool = False
    pending_kind: str | None = None
    pending_text: str | None = None
    pending_attempts: int = 0
    created_at: int = 0
    updated_at: int = 0


def format_sector_sync_text(result: RetainedResult) -> str:
    """Render the Vietnamese notification body for one retained result."""
    if result.sector_code is None:
        return (
            f"⚠️ Không thể đồng bộ ngành cho {result.requested_symbol}: "
            "chưa có phân loại ngành hiệu lực."
        )
    if result.ready:
        return (
            f"✅ Dữ liệu ngành {result.requested_symbol} đã sẵn sàng: "
            f"{result.usable}/{result.members} mã đủ lịch sử.\n"
            "Bấm “Xem lại ASMF” để cập nhật phân tích."
        )
    return (
        f"⚠️ Đồng bộ ngành {result.requested_symbol} chưa đủ: "
        f"{result.usable}/{result.members} mã đủ lịch sử; "
        f"{result.failed_count} mã thất bại trong lượt này.\n"
        "Bot sẽ tự thử lại ở chu kỳ sau."
    )


def pending_kind_for(result: RetainedResult) -> str:
    if result.sector_code is None:
        return PENDING_UNAVAILABLE
    return PENDING_READY if result.ready else PENDING_INCOMPLETE


class InMemoryNotificationStore:
    """Non-durable store preserving the original RAM-only semantics."""

    persistent = False

    def __init__(self) -> None:
        self._watchers: dict[tuple[str, str], WatcherState] = {}
        self._results: dict[str, tuple[RetainedResult, str, int]] = {}

    # ------------------------------------------------------------- watchers
    def load_watcher(self, chat_id: str, symbol: str) -> WatcherState | None:
        return self._watchers.get((chat_id, symbol))

    def save_watcher(self, watcher: WatcherState) -> None:
        self._watchers[(watcher.chat_id, watcher.symbol)] = watcher

    def delete_watcher(self, chat_id: str, symbol: str) -> None:
        self._watchers.pop((chat_id, symbol), None)

    def open_watchers(self, symbol: str) -> tuple[WatcherState, ...]:
        return tuple(
            watcher for watcher in self._watchers.values()
            if watcher.symbol == symbol and not watcher.closed
        )

    def pending_watchers(self) -> tuple[WatcherState, ...]:
        return tuple(sorted(
            (w for w in self._watchers.values() if w.pending_kind is not None),
            key=lambda w: (w.updated_at, w.symbol, w.chat_id),
        ))

    # -------------------------------------------------------------- results
    def load_result(self, symbol: str) -> tuple[RetainedResult, str] | None:
        stored = self._results.get(symbol)
        return None if stored is None else (stored[0], stored[1])

    def save_result(self, result: RetainedResult, now: int) -> None:
        self._results[result.requested_symbol] = (result, result.fingerprint, now)

    # -------------------------------------------------------------- cleanup
    def purge(self, cutoff: int) -> int:
        removed = 0
        for key, watcher in tuple(self._watchers.items()):
            if watcher.pending_kind is None and watcher.updated_at < cutoff:
                del self._watchers[key]
                removed += 1
        for symbol, stored in tuple(self._results.items()):
            if stored[2] < cutoff:
                del self._results[symbol]
        return removed


class SQLiteNotificationStore:
    """Durable store backed by the existing main runtime SQLite database."""

    persistent = True

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
        *,
        bootstrap: Callable[[sqlite3.Connection], int] | None = None,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        self._connection_factory = connection_factory
        if bootstrap is None:
            from data.migrations import bootstrap_schema as bootstrap
        connection = self._connection_factory()
        try:
            bootstrap(connection)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = self._connection_factory()
        connection.row_factory = sqlite3.Row
        return connection

    # ------------------------------------------------------------- watchers
    def load_watcher(self, chat_id: str, symbol: str) -> WatcherState | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM sector_sync_watchers WHERE chat_id=? AND symbol=?",
                (chat_id, symbol),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _watcher_from_row(row)

    def save_watcher(self, watcher: WatcherState) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO sector_sync_watchers("
                    "chat_id,symbol,incomplete_sent,closed,pending_kind,"
                    "pending_text,pending_attempts,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(chat_id,symbol) DO UPDATE SET "
                    "incomplete_sent=excluded.incomplete_sent,"
                    "closed=excluded.closed,"
                    "pending_kind=excluded.pending_kind,"
                    "pending_text=excluded.pending_text,"
                    "pending_attempts=excluded.pending_attempts,"
                    "updated_at=excluded.updated_at",
                    (
                        watcher.chat_id, watcher.symbol,
                        1 if watcher.incomplete_sent else 0,
                        1 if watcher.closed else 0,
                        watcher.pending_kind, watcher.pending_text,
                        watcher.pending_attempts,
                        watcher.created_at, watcher.updated_at,
                    ),
                )
        finally:
            connection.close()

    def delete_watcher(self, chat_id: str, symbol: str) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "DELETE FROM sector_sync_watchers WHERE chat_id=? AND symbol=?",
                    (chat_id, symbol),
                )
        finally:
            connection.close()

    def open_watchers(self, symbol: str) -> tuple[WatcherState, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM sector_sync_watchers "
                "WHERE symbol=? AND closed=0 ORDER BY created_at, chat_id",
                (symbol,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_watcher_from_row(row) for row in rows)

    def pending_watchers(self) -> tuple[WatcherState, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM sector_sync_watchers "
                "WHERE pending_kind IS NOT NULL "
                "ORDER BY updated_at, symbol, chat_id"
            ).fetchall()
        finally:
            connection.close()
        return tuple(_watcher_from_row(row) for row in rows)

    # -------------------------------------------------------------- results
    def load_result(self, symbol: str) -> tuple[RetainedResult, str] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM sector_sync_results WHERE symbol=?", (symbol,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        retained = RetainedResult(
            requested_symbol=row["symbol"],
            sector_code=row["sector_code"],
            members=int(row["members"]),
            usable=int(row["usable"]),
            failed_count=int(row["failed"]),
        )
        return retained, str(row["fingerprint"])

    def save_result(self, result: RetainedResult, now: int) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    "INSERT INTO sector_sync_results("
                    "symbol,sector_code,members,usable,failed,ready,"
                    "fingerprint,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(symbol) DO UPDATE SET "
                    "sector_code=excluded.sector_code,"
                    "members=excluded.members,usable=excluded.usable,"
                    "failed=excluded.failed,ready=excluded.ready,"
                    "fingerprint=excluded.fingerprint,"
                    "updated_at=excluded.updated_at",
                    (
                        result.requested_symbol, result.sector_code,
                        result.members, result.usable, result.failed_count,
                        1 if result.ready else 0, result.fingerprint, now,
                    ),
                )
        finally:
            connection.close()

    # -------------------------------------------------------------- cleanup
    def purge(self, cutoff: int) -> int:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM sector_sync_watchers "
                    "WHERE pending_kind IS NULL AND updated_at < ?", (cutoff,),
                )
                removed = int(cursor.rowcount or 0)
                connection.execute(
                    "DELETE FROM sector_sync_results WHERE updated_at < ?",
                    (cutoff,),
                )
        finally:
            connection.close()
        return removed


def _watcher_from_row(row: sqlite3.Row) -> WatcherState:
    return WatcherState(
        chat_id=str(row["chat_id"]),
        symbol=str(row["symbol"]),
        incomplete_sent=bool(row["incomplete_sent"]),
        closed=bool(row["closed"]),
        pending_kind=row["pending_kind"],
        pending_text=row["pending_text"],
        pending_attempts=int(row["pending_attempts"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
    )


def cleared(watcher: WatcherState, now: int) -> WatcherState:
    """Return the watcher with its queued notification removed."""
    return replace(
        watcher, pending_kind=None, pending_text=None,
        pending_attempts=0, updated_at=now,
    )

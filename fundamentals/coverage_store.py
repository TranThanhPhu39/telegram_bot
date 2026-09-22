"""Persistence for automated acquisition staging rows and coverage status.

This is additive to the existing SQLite database (migration v7) and does not
replace ``asmf_data.store``: statement rows land here first, are optionally
promoted into the existing canonical tables via ``fundamentals.adapters``,
and institutional flow rows are upserted directly through the existing
``asmf_data.store.upsert_institutional_flows`` since that table already
tolerates per-field NULLs and carries no point-in-time risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import sqlite3
from typing import Iterable

from fundamentals.providers.base import (
    STATEMENT_FIELDS, BANK_FIELDS, ProviderResult, ProviderStatus, StatementRow,
)
from runtime.redaction import safe_reason

#: symbol_data_coverage.status uses this project's coverage vocabulary, which
#: is not identical to ProviderStatus (AVAILABLE from one refresh means the
#: dataset is READY as of that refresh, not merely "available this instant").
_COVERAGE_STATUS_FROM_PROVIDER_STATUS = {
    ProviderStatus.AVAILABLE: "READY",
    ProviderStatus.PARTIAL: "PARTIAL",
    ProviderStatus.MISSING: "MISSING",
    ProviderStatus.STALE: "STALE",
    ProviderStatus.ERROR: "ERROR",
}

COVERAGE_STATES = (
    "NEVER_ATTEMPTED", "READY", "PARTIAL", "MISSING", "STALE", "ERROR", "IN_PROGRESS",
)

#: Datasets tracked in ``symbol_data_coverage``. FINANCIALS/INSTITUTIONAL come
#: from the Phase 24 provider chain; the rest were added by migration v8 for the
#: Phase 25 coverage worker.
PROVIDER_DATASETS = ("FINANCIALS", "INSTITUTIONAL")
COVERAGE_DATASETS = (
    "FINANCIALS", "INSTITUTIONAL", "MARKET_HISTORY", "SECTOR_HISTORY", "NEWS",
)

#: States that count as "we hold usable data" (a success timestamp is recorded).
SUCCESS_STATES = ("READY", "PARTIAL")

#: An IN_PROGRESS marker older than this is treated as abandoned (the process
#: died mid-refresh) and the dataset becomes due again.
DEFAULT_IN_PROGRESS_LEASE_SECONDS = 1800.0


@dataclass(frozen=True, slots=True)
class CoverageStatus:
    symbol: str
    dataset: str
    status: str
    provider: str | None
    provider_source: str | None
    error_reason: str | None
    attempts: int
    last_attempt_at: int | None
    last_success_at: int | None
    updated_at: int

    @property
    def last_attempt(self) -> datetime | None:
        return None if self.last_attempt_at is None else datetime.fromtimestamp(
            self.last_attempt_at, tz=timezone.utc
        )

    @property
    def last_success(self) -> datetime | None:
        return None if self.last_success_at is None else datetime.fromtimestamp(
            self.last_success_at, tz=timezone.utc
        )


def coverage_is_stale(status: CoverageStatus, max_age_seconds: float, *, now: datetime | None = None) -> bool:
    """A dataset is stale when it was never fetched, or the last success aged out."""
    if status.last_success_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    age = current.timestamp() - status.last_success_at
    return age > max_age_seconds


def _ensure_symbol(connection: sqlite3.Connection, symbol: str) -> None:
    with connection:
        connection.execute(
            "INSERT INTO symbols(symbol,instrument_type) VALUES (?,'STOCK') "
            "ON CONFLICT(symbol) DO NOTHING",
            (symbol,),
        )


def upsert_automated_statement(
    connection: sqlite3.Connection, row: StatementRow, *, provider: str,
    provider_source: str | None, promoted: bool, now: datetime | None = None,
) -> None:
    """Idempotent by (symbol, period, source): a rerun overwrites, not duplicates."""
    _ensure_symbol(connection, row.symbol)
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    source = f"{provider}/{provider_source}" if provider_source else provider
    columns = {name: row.get(name) for name in (*STATEMENT_FIELDS, *BANK_FIELDS)}
    fields = (
        "symbol", "period", "source", "provider", "provider_source", "public_date",
        "consolidated", *STATEMENT_FIELDS,
        "net_interest_income", "bank_net_profit", "bank_equity", "gross_loans",
        "nonperforming_loans", "loan_loss_reserve", "car_percent",
        "retrieved_at", "promoted_to_canonical",
    )
    from fundamentals.adapters import resolve_public_date
    effective_date, _ = resolve_public_date(row)
    values = (
        row.symbol, row.period, source, provider, provider_source,
        None if effective_date is None else effective_date.isoformat(),
        int(row.consolidated),
        *(columns[name] for name in STATEMENT_FIELDS),
        columns.get("net_interest_income"),
        columns.get("net_profit"),   # BANK_FIELDS reuses "net_profit"/"equity" labels
        columns.get("equity"),
        columns.get("gross_loans"), columns.get("nonperforming_loans"),
        columns.get("loan_loss_reserve"), columns.get("car_percent"),
        stamp, int(promoted),
    )
    placeholders = ",".join("?" for _ in fields)
    update_clause = ",".join(f"{name}=excluded.{name}" for name in fields if name not in ("symbol", "period", "source"))
    with connection:
        connection.execute(
            f"INSERT INTO automated_financial_statements({','.join(fields)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(symbol,period,source) DO UPDATE SET {update_clause}",
            values,
        )


def load_automated_statements(
    connection: sqlite3.Connection, symbol: str
) -> tuple[sqlite3.Row, ...]:
    return tuple(connection.execute(
        "SELECT * FROM automated_financial_statements WHERE symbol=? ORDER BY period DESC",
        (symbol.strip().upper(),),
    ).fetchall())


def record_attempt(
    connection: sqlite3.Connection, symbol: str, dataset: str, status: str, *,
    provider: str | None = None, provider_source: str | None = None,
    error_reason: str | None = None, now: datetime | None = None,
) -> CoverageStatus:
    """Persist one attempt's outcome for any coverage dataset.

    The single write path for coverage rows: every attempt increments
    ``attempts`` and stamps ``last_attempt_at``; ``last_success_at`` only moves
    forward on READY/PARTIAL, so a later ERROR/MISSING never erases the last
    time data was actually obtained.
    """
    if dataset not in COVERAGE_DATASETS:
        raise ValueError(f"unknown coverage dataset: {dataset!r}")
    if status not in COVERAGE_STATES or status in ("NEVER_ATTEMPTED", "IN_PROGRESS"):
        raise ValueError(f"record_attempt cannot persist status {status!r}")
    symbol = symbol.strip().upper()
    _ensure_symbol(connection, symbol)
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    success = status in SUCCESS_STATES
    reason = None if error_reason is None else safe_reason(error_reason)
    with connection:
        connection.execute(
            "INSERT INTO symbol_data_coverage("
            "symbol,dataset,status,provider,provider_source,error_reason,"
            "attempts,last_attempt_at,last_success_at,updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?) "
            "ON CONFLICT(symbol,dataset) DO UPDATE SET "
            "status=excluded.status,provider=excluded.provider,"
            "provider_source=excluded.provider_source,error_reason=excluded.error_reason,"
            "attempts=symbol_data_coverage.attempts+1,"
            "last_attempt_at=excluded.last_attempt_at,"
            "last_success_at=CASE WHEN ? THEN excluded.last_attempt_at "
            "ELSE symbol_data_coverage.last_success_at END,"
            "updated_at=excluded.updated_at",
            (
                symbol, dataset, status, provider, provider_source, reason,
                stamp, stamp if success else None, stamp, 1 if success else 0,
            ),
        )
    return load_coverage(connection, symbol, dataset)  # type: ignore[return-value]


def record_coverage(
    connection: sqlite3.Connection, symbol: str, dataset: str, result: ProviderResult,
    *, now: datetime | None = None,
) -> CoverageStatus:
    """Update the per-symbol/dataset coverage row from one provider refresh."""
    if dataset not in PROVIDER_DATASETS:
        raise ValueError("dataset must be FINANCIALS or INSTITUTIONAL")
    return record_attempt(
        connection, symbol, dataset, _COVERAGE_STATUS_FROM_PROVIDER_STATUS[result.status],
        provider=result.provider, provider_source=result.provider_source,
        error_reason=result.error_reason, now=now,
    )


def record_attempts_bulk(
    connection: sqlite3.Connection, dataset: str,
    rows: Iterable[tuple[str, str, str | None, str | None, str | None]], *,
    now: datetime | None = None,
) -> int:
    """Record many symbols' outcomes for one dataset in a single transaction.

    Each row is ``(symbol, status, provider, provider_source, error_reason)``.
    Semantics match :func:`record_attempt` (attempts+1, last_success only moves
    on READY/PARTIAL). Symbols must already exist in ``symbols``; unlike the
    single-row path this never creates one, because bulk callers project an
    already-known universe onto coverage.
    """
    if dataset not in COVERAGE_DATASETS:
        raise ValueError(f"unknown coverage dataset: {dataset!r}")
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    payload = []
    for symbol, status, provider, source, reason in rows:
        if status not in COVERAGE_STATES or status in ("NEVER_ATTEMPTED", "IN_PROGRESS"):
            raise ValueError(f"record_attempts_bulk cannot persist status {status!r}")
        success = 1 if status in SUCCESS_STATES else 0
        payload.append((
            symbol.strip().upper(), dataset, status, provider, source,
            None if reason is None else safe_reason(reason),
            stamp, stamp if success else None, stamp, success,
        ))
    if not payload:
        return 0
    with connection:
        connection.executemany(
            "INSERT INTO symbol_data_coverage("
            "symbol,dataset,status,provider,provider_source,error_reason,"
            "attempts,last_attempt_at,last_success_at,updated_at) "
            "VALUES (?,?,?,?,?,?,1,?,?,?) "
            "ON CONFLICT(symbol,dataset) DO UPDATE SET "
            "status=excluded.status,provider=excluded.provider,"
            "provider_source=excluded.provider_source,error_reason=excluded.error_reason,"
            "attempts=symbol_data_coverage.attempts+1,"
            "last_attempt_at=excluded.last_attempt_at,"
            "last_success_at=CASE WHEN ? THEN excluded.last_attempt_at "
            "ELSE symbol_data_coverage.last_success_at END,"
            "updated_at=excluded.updated_at",
            payload,
        )
    return len(payload)


def mark_in_progress_bulk(
    connection: sqlite3.Connection, dataset: str, symbols: Iterable[str], *,
    now: datetime | None = None,
) -> int:
    """Flag many symbols IN_PROGRESS for one dataset in one transaction."""
    if dataset not in COVERAGE_DATASETS:
        raise ValueError(f"unknown coverage dataset: {dataset!r}")
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    payload = [(symbol.strip().upper(), dataset, stamp, stamp) for symbol in symbols]
    if not payload:
        return 0
    with connection:
        connection.executemany(
            "INSERT INTO symbol_data_coverage("
            "symbol,dataset,status,attempts,last_attempt_at,updated_at) "
            "VALUES (?,?,'IN_PROGRESS',0,?,?) "
            "ON CONFLICT(symbol,dataset) DO UPDATE SET "
            "status='IN_PROGRESS',last_attempt_at=excluded.last_attempt_at,"
            "updated_at=excluded.updated_at",
            payload,
        )
    return len(payload)


def coverage_counts(
    connection: sqlite3.Connection, dataset: str,
) -> dict[str, int]:
    """Persisted status histogram for one dataset (no aging applied)."""
    rows = connection.execute(
        "SELECT status, COUNT(*) AS n FROM symbol_data_coverage WHERE dataset=? GROUP BY status",
        (dataset,),
    ).fetchall()
    return {row["status"]: int(row["n"]) for row in rows}


def mark_in_progress(
    connection: sqlite3.Connection, symbol: str, dataset: str, *,
    now: datetime | None = None,
) -> None:
    """Flag a refresh as running without touching attempts or last_success_at.

    The marker survives a crash, which is the point: on restart the worker sees
    an IN_PROGRESS row whose lease has expired and reclaims it.
    """
    if dataset not in COVERAGE_DATASETS:
        raise ValueError(f"unknown coverage dataset: {dataset!r}")
    symbol = symbol.strip().upper()
    _ensure_symbol(connection, symbol)
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    with connection:
        connection.execute(
            "INSERT INTO symbol_data_coverage("
            "symbol,dataset,status,attempts,last_attempt_at,updated_at) "
            "VALUES (?,?,'IN_PROGRESS',0,?,?) "
            "ON CONFLICT(symbol,dataset) DO UPDATE SET "
            "status='IN_PROGRESS',last_attempt_at=excluded.last_attempt_at,"
            "updated_at=excluded.updated_at",
            (symbol, dataset, stamp, stamp),
        )


def mark_stale(
    connection: sqlite3.Connection, dataset: str, max_age_seconds: float, *,
    now: datetime | None = None,
) -> int:
    """Persist STALE for READY/PARTIAL rows whose last success aged out.

    Idempotent (a STALE row is no longer READY/PARTIAL), one statement, and it
    never invents data: ``last_success_at`` and the provider are left as-is so
    the row still says where the old data came from.
    """
    if dataset not in COVERAGE_DATASETS:
        raise ValueError(f"unknown coverage dataset: {dataset!r}")
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    with connection:
        cursor = connection.execute(
            "UPDATE symbol_data_coverage SET status='STALE',updated_at=? "
            "WHERE dataset=? AND status IN ('READY','PARTIAL') "
            "AND last_success_at IS NOT NULL AND (? - last_success_at) > ?",
            (stamp, dataset, stamp, max_age_seconds),
        )
    return cursor.rowcount


def effective_status(
    status: CoverageStatus | None, refresh_interval_seconds: float, *,
    now: datetime | None = None,
    in_progress_lease_seconds: float = DEFAULT_IN_PROGRESS_LEASE_SECONDS,
) -> str:
    """Status as of ``now``: ages READY/PARTIAL into STALE, expires abandoned IN_PROGRESS.

    Pure read-side view, so a report shows the truth even between worker sweeps.
    """
    if status is None:
        return "NEVER_ATTEMPTED"
    current = (now or datetime.now(timezone.utc)).timestamp()
    if status.status == "IN_PROGRESS":
        started = status.last_attempt_at or status.updated_at
        return "IN_PROGRESS" if current - started <= in_progress_lease_seconds else "STALE"
    if status.status in SUCCESS_STATES:
        if status.last_success_at is None or current - status.last_success_at > refresh_interval_seconds:
            return "STALE"
    return status.status


def load_coverage(connection: sqlite3.Connection, symbol: str, dataset: str) -> CoverageStatus | None:
    row = connection.execute(
        "SELECT * FROM symbol_data_coverage WHERE symbol=? AND dataset=?",
        (symbol.strip().upper(), dataset),
    ).fetchone()
    return None if row is None else _status_from_row(row)


def load_all_coverage(connection: sqlite3.Connection, dataset: str | None = None) -> tuple[CoverageStatus, ...]:
    if dataset is None:
        rows = connection.execute(
            "SELECT * FROM symbol_data_coverage ORDER BY symbol, dataset"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM symbol_data_coverage WHERE dataset=? ORDER BY symbol", (dataset,)
        ).fetchall()
    return tuple(_status_from_row(row) for row in rows)


def _status_from_row(row: sqlite3.Row | tuple) -> CoverageStatus:
    if isinstance(row, tuple):
        return CoverageStatus(
            symbol=row[0], dataset=row[1], status=row[2],
            provider=row[3], provider_source=row[4],
            error_reason=row[5], attempts=int(row[6]),
            last_attempt_at=row[7], last_success_at=row[8],
            updated_at=int(row[9]),
        )
    return CoverageStatus(
        symbol=row["symbol"], dataset=row["dataset"], status=row["status"],
        provider=row["provider"], provider_source=row["provider_source"],
        error_reason=row["error_reason"], attempts=int(row["attempts"]),
        last_attempt_at=row["last_attempt_at"], last_success_at=row["last_success_at"],
        updated_at=int(row["updated_at"]),
    )

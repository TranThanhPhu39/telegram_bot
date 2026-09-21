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
    values = (
        row.symbol, row.period, source, provider, provider_source,
        None if row.public_date is None else row.public_date.isoformat(),
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


def record_coverage(
    connection: sqlite3.Connection, symbol: str, dataset: str, result: ProviderResult,
    *, now: datetime | None = None,
) -> CoverageStatus:
    """Update the per-symbol/dataset coverage row from one refresh attempt."""
    if dataset not in ("FINANCIALS", "INSTITUTIONAL"):
        raise ValueError("dataset must be FINANCIALS or INSTITUTIONAL")
    symbol = symbol.strip().upper()
    _ensure_symbol(connection, symbol)
    stamp = int((now or datetime.now(timezone.utc)).timestamp())
    status = _COVERAGE_STATUS_FROM_PROVIDER_STATUS[result.status]
    success = result.status.usable
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
                symbol, dataset, status, result.provider, result.provider_source,
                result.error_reason, stamp, stamp if success else None, stamp,
                1 if success else 0,
            ),
        )
    return load_coverage(connection, symbol, dataset)  # type: ignore[return-value]


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


def _status_from_row(row: sqlite3.Row) -> CoverageStatus:
    return CoverageStatus(
        symbol=row["symbol"], dataset=row["dataset"], status=row["status"],
        provider=row["provider"], provider_source=row["provider_source"],
        error_reason=row["error_reason"], attempts=int(row["attempts"]),
        last_attempt_at=row["last_attempt_at"], last_success_at=row["last_success_at"],
        updated_at=int(row["updated_at"]),
    )

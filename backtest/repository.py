"""SQLite persistence for reproducible strategy-backtest summaries."""

from __future__ import annotations

from datetime import date
import json
import sqlite3

from backtest.models import BacktestRun, BacktestRunStatus, BacktestValidationStatus


_COLUMNS = (
    "run_id", "strategy", "run_kind", "validation_status", "status",
    "started_at", "completed_at", "start_date", "end_date", "universe_size",
    "symbols_json", "initial_capital", "final_equity", "trade_count",
    "open_position_count", "total_return_percent", "cagr_percent",
    "max_drawdown_percent", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
    "win_rate_percent", "average_return_percent", "profit_factor",
    "expectancy_percent", "average_win_percent", "average_loss_percent",
    "payoff_ratio", "best_trade_percent", "worst_trade_percent",
    "average_holding_sessions", "longest_losing_streak", "exposure_percent",
    "trades_per_year", "benchmark_return_percent",
    "benchmark_max_drawdown_percent", "excess_return_percent", "config_json",
    "warnings_json", "created_at",
)


def save_backtest_run(connection: sqlite3.Connection, run: BacktestRun) -> None:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    if not isinstance(run, BacktestRun):
        raise TypeError("run must be a BacktestRun")
    values = _to_values(run)
    assignments = ",".join(
        f"{column}=excluded.{column}" for column in _COLUMNS if column not in {"run_id", "created_at"}
    )
    placeholders = ",".join("?" for _ in _COLUMNS)
    with connection:
        connection.execute(
            f"INSERT INTO backtest_runs ({','.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(run_id) DO UPDATE SET {assignments}",
            values,
        )


def latest_successful_backtest(
    connection: sqlite3.Connection, strategy: str
) -> BacktestRun | None:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    normalized = strategy.strip().upper()
    if normalized not in {"CL1", "ASMF"}:
        raise ValueError("strategy must be CL1 or ASMF")
    row = connection.execute(
        "SELECT * FROM backtest_runs WHERE strategy=? AND status='SUCCESS' "
        "ORDER BY completed_at DESC, created_at DESC, run_id DESC LIMIT 1",
        (normalized,),
    ).fetchone()
    return None if row is None else _from_row(row)


def latest_successful_backtests(connection: sqlite3.Connection) -> dict[str, BacktestRun | None]:
    return {
        strategy: latest_successful_backtest(connection, strategy)
        for strategy in ("CL1", "ASMF")
    }


def _to_values(run: BacktestRun) -> tuple[object, ...]:
    values = {
        "run_id": run.run_id,
        "strategy": run.strategy,
        "run_kind": run.run_kind,
        "validation_status": run.validation_status.value,
        "status": run.status.value,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "start_date": run.start_date.isoformat(),
        "end_date": run.end_date.isoformat(),
        "universe_size": len(run.symbols),
        "symbols_json": json.dumps(run.symbols, ensure_ascii=False, separators=(",", ":")),
        "initial_capital": run.initial_capital,
        "final_equity": run.final_equity,
        "trade_count": run.trade_count,
        "open_position_count": run.open_position_count,
        "config_json": json.dumps(run.config, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "warnings_json": json.dumps(run.warnings, ensure_ascii=False, separators=(",", ":")),
        "created_at": run.created_at or run.started_at,
    }
    for name in _METRIC_COLUMNS:
        values[name] = getattr(run, name)
    return tuple(values[column] for column in _COLUMNS)


def _from_row(row: sqlite3.Row) -> BacktestRun:
    values = {name: row[name] for name in _METRIC_COLUMNS}
    return BacktestRun(
        run_id=row["run_id"], strategy=row["strategy"],
        run_kind=row["run_kind"],
        validation_status=BacktestValidationStatus(row["validation_status"]),
        status=BacktestRunStatus(row["status"]), started_at=row["started_at"],
        completed_at=row["completed_at"], start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]),
        symbols=tuple(json.loads(row["symbols_json"])),
        initial_capital=row["initial_capital"], final_equity=row["final_equity"],
        trade_count=row["trade_count"], open_position_count=row["open_position_count"],
        config=json.loads(row["config_json"]), warnings=tuple(json.loads(row["warnings_json"])),
        created_at=row["created_at"], **values,
    )


_METRIC_COLUMNS = _COLUMNS[15:37]

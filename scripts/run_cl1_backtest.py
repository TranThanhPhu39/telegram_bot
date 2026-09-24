"""Run and persist a CL1 historical signal evaluation from cached daily bars."""

from __future__ import annotations

import argparse
from datetime import date
import os
import sys

from dotenv import load_dotenv

from backtest.data import SQLiteDailyBarData
from backtest.execution import BacktestExecutionConfig
from backtest.runner import run_strategy_backtest
from data.database import connect_database
from data.migrations import bootstrap_schema


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Run and persist a cost-aware CL1 historical backtest."
    )
    value.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. FPT,ACB")
    value.add_argument("--start-date", required=True, type=date.fromisoformat)
    value.add_argument("--end-date", required=True, type=date.fromisoformat)
    value.add_argument("--initial-capital", type=float, default=500_000_000.0)
    value.add_argument("--settlement-sessions", type=int, required=True,
                       help="Caller-supplied trading-session convention; no T+2/T+2.5 default is assumed")
    value.add_argument("--commission-rate", type=float, default=0.0015)
    value.add_argument("--sell-tax-rate", type=float, default=0.0010)
    value.add_argument("--slippage-rate", type=float, default=0.0020)
    value.add_argument("--lot-size", type=int, default=100)
    value.add_argument("--run-id")
    return value


def main(arguments: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    args = parser().parse_args(arguments)
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    try:
        bootstrap_schema(connection)
        result = run_strategy_backtest(
            strategy="CL1", symbols=symbols, start_date=args.start_date,
            end_date=args.end_date, data_port=SQLiteDailyBarData(connection),
            connection=connection, initial_capital=args.initial_capital,
            run_id=args.run_id,
            execution_config=BacktestExecutionConfig(
                settlement_sessions=args.settlement_sessions,
                commission_rate=args.commission_rate,
                sell_tax_rate=args.sell_tax_rate,
                slippage_rate=args.slippage_rate,
                lot_size=args.lot_size,
                initial_capital=args.initial_capital,
            ),
        )
    except (TypeError, ValueError) as error:
        print(f"[FAIL] {error}")
        return 1
    finally:
        connection.close()
    counts = result.run.config["action_counts"]
    print(
        f"[PASS] CL1 historical BACKTEST; run_id={result.run.run_id}; "
        f"symbols={len(result.run.symbols)}; decisions={result.run.config['decision_count']}; "
        f"trades={result.run.trade_count}; actions={counts}"
    )
    print("STATUS: IN_SAMPLE_ONLY; returns are net of configured fee/tax/slippage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

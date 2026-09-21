"""Shared plumbing for the bounded manual coverage scripts.

Each script is a thin wrapper over :class:`runtime.coverage_worker.MarketCoverageEngine`
so manual runs use exactly the same selection, freshness, retry/backoff and
failure-isolation rules as the background worker. Scripts run ONE bounded cycle
and exit; none of them loops.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from collections.abc import Sequence

if __package__ in {None, ""}:  # allow `python scripts/x.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.migrations import bootstrap_schema
from runtime.coverage_config import CoverageConfig
from runtime.coverage_factory import (
    build_engine_from_env,
    connection_factory_from_env,
)
from runtime.redaction import configure_logging, redact_secrets


def build_parser(description: str, *, with_datasets: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--symbol", "-s", nargs="+", action="extend", metavar="SYMBOL", default=None,
        help="restrict to these symbols (must exist in the symbols table)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="maximum symbols this run (default: COVERAGE_BATCH_SIZE)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="refresh even when data is fresh or a cooldown is active",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be refreshed; make no provider call and no write",
    )
    if with_datasets:
        parser.add_argument(
            "--datasets", default=None,
            help="comma-separated subset of FINANCIALS,INSTITUTIONAL,MARKET_HISTORY,"
                 "SECTOR_HISTORY,NEWS (default: COVERAGE_DATASETS)",
        )
    return parser


def run_cycle_cli(
    argv: Sequence[str] | None, *, description: str, datasets: tuple[str, ...] | None,
    with_datasets: bool = False,
) -> int:
    parser = build_parser(description, with_datasets=with_datasets)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    load_dotenv()
    configure_logging()
    config = CoverageConfig.from_env()
    chosen = datasets
    if with_datasets and args.datasets:
        chosen = tuple(
            part.strip().upper() for part in args.datasets.split(",") if part.strip()
        )
    factory = connection_factory_from_env()
    engine = build_engine_from_env(config, connection_factory=factory)
    try:
        bootstrap_schema(engine.connection)
        symbols = None if args.symbol is None else tuple(args.symbol)
        if args.dry_run:
            plan = engine.preview(
                symbols=symbols, limit=args.limit, force=args.force, datasets=chosen
            )
            print(f"dry-run: {len(plan)} symbol(s) would be processed")
            for symbol, due in plan:
                print(f"  {symbol}: {', '.join(due)}")
            return 0
        report = engine.run_cycle(
            symbols=symbols, limit=args.limit, force=args.force, datasets=chosen
        )
        for outcome in report.outcomes:
            line = (
                f"{outcome.symbol} {outcome.dataset} {outcome.result} "
                f"provider={outcome.provider or '-'} attempts={outcome.attempts}"
            )
            if outcome.detail:
                line += f" reason={outcome.detail}"
            print(redact_secrets(line))
        if not report.outcomes and report.due_symbols == 0:
            print("nothing due: every requested dataset is fresh or cooling down")
        print(redact_secrets(report.summary()))
        failed = any(o.result == "FAILED" for o in report.outcomes)
        return 1 if failed else 0
    finally:
        engine.close()
        engine.connection.close()


def database_url() -> str:
    load_dotenv()
    return os.getenv("DATABASE_URL", "sqlite:///stock_bot.db")

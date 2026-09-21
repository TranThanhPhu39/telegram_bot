"""Print the market data coverage report from the runtime database (read-only)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.database import connect_database
from fundamentals.coverage_store import COVERAGE_DATASETS
from runtime.coverage_config import CoverageConfig
from runtime.coverage_report import (
    STATUS_ORDER,
    build_coverage_report,
    render_report,
    render_status_listing,
    render_symbol_detail,
)
from runtime.redaction import redact_secrets
from scripts.coverage_cli import database_url


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", help="show every dataset's coverage row for one symbol")
    parser.add_argument("--dataset", choices=COVERAGE_DATASETS, help="limit to one dataset")
    parser.add_argument("--status", choices=STATUS_ORDER,
                        help="with --dataset: list the symbols in that status")
    parser.add_argument("--limit", type=int, default=50, help="max symbols to list")
    args = parser.parse_args(argv)
    if args.status and not args.dataset:
        parser.error("--status requires --dataset")
    load_dotenv()
    connection = connect_database(database_url())
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not {"symbols", "symbol_data_coverage"} <= tables:
            print("database has no coverage tables yet; run the bot or "
                  "scripts/sync_market_coverage.py once to initialise it")
            return 2
        config = CoverageConfig.from_env()
        if args.symbol:
            print(redact_secrets(render_symbol_detail(connection, args.symbol, config)))
            return 0
        report = build_coverage_report(
            connection, config,
            datasets=None if args.dataset is None else (args.dataset,),
        )
        print(render_report(report))
        if args.dataset and args.status:
            print()
            print(render_status_listing(report, args.dataset, args.status, args.limit))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

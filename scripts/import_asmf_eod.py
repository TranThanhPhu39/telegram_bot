"""Import normalized CafeF/Vietstock/manual EOD exports into SQLite."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from asmf_data.csv_source import load_financial_csv, load_flow_csv, load_sector_csv
from asmf_data.store import upsert_financial_reports, upsert_institutional_flows, upsert_sector_memberships
from data.database import connect_database
from data.migrations import bootstrap_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sectors")
    parser.add_argument("--financials")
    parser.add_argument("--flows")
    args = parser.parse_args()
    if not any((args.sectors, args.financials, args.flows)):
        parser.error("provide at least one of --sectors, --financials, or --flows")
    load_dotenv()
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    bootstrap_schema(connection)
    try:
        if args.sectors:
            print(f"sectors: {upsert_sector_memberships(connection, load_sector_csv(args.sectors))}")
        if args.financials:
            print(f"financials: {upsert_financial_reports(connection, load_financial_csv(args.financials))}")
        if args.flows:
            print(f"flows: {upsert_institutional_flows(connection, load_flow_csv(args.flows))}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

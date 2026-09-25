"""Import point-in-time VNAllshare sector memberships from a local HOSE PDF."""

from __future__ import annotations

import argparse
from datetime import date
import os

from dotenv import load_dotenv

from asmf_data.hose_sector_pdf import (
    extract_pdf_pages,
    extract_vnallshare_symbols,
    parse_hose_sector_pdf,
    sector_counts,
)
from asmf_data.store import upsert_sector_memberships
from data.database import connect_database
from data.migrations import bootstrap_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--effective-from", required=True, type=date.fromisoformat)
    parser.add_argument("--effective-to", type=date.fromisoformat)
    parser.add_argument("--source", required=True)
    parser.add_argument("--include-sector", action="append", default=[])
    parser.add_argument("--eligible-symbols-pdf")
    parser.add_argument("--expect-count", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = parse_hose_sector_pdf(
        args.pdf,
        effective_from=args.effective_from,
        effective_to=args.effective_to,
        source=args.source,
        include_codes=frozenset(args.include_sector) if args.include_sector else None,
    )
    if args.eligible_symbols_pdf:
        eligible = extract_vnallshare_symbols(extract_pdf_pages(args.eligible_symbols_pdf))
        rows = tuple(row for row in rows if row.symbol in eligible)
    counts = sector_counts(rows)
    expected = _expected_counts(args.expect_count)
    mismatches = {
        code: (count, counts.get(code, 0))
        for code, count in expected.items()
        if counts.get(code, 0) != count
    }
    if mismatches:
        details = ", ".join(
            f"{code} expected={wanted} actual={actual}"
            for code, (wanted, actual) in sorted(mismatches.items())
        )
        raise ValueError(f"sector count validation failed: {details}")
    summary = " ".join(f"{code}={count}" for code, count in counts.items())
    if args.dry_run:
        print(f"DRY RUN: sectors={len(rows)} {summary}")
        return 0

    load_dotenv()
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    bootstrap_schema(connection)
    try:
        imported = upsert_sector_memberships(connection, rows)
    finally:
        connection.close()
    print(f"sectors: {imported} {summary}")
    return 0


def _expected_counts(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        code, separator, count = value.partition("=")
        if not separator or not code.strip() or not count.isdigit():
            raise ValueError("--expect-count must use CODE=COUNT")
        result[code.strip().upper()] = int(count)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

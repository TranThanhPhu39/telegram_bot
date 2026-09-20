"""Fetch one effective-dated Vietcap ICB2 membership snapshot as CSV."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import os
from pathlib import Path

from dotenv import load_dotenv

from asmf_data.vietcap_sectors import VietcapSectorClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv()
    client = VietcapSectorClient(
        authorization=os.getenv("VIETCAP_AUTHORIZATION", ""),
        device_id=os.getenv("VIETCAP_DEVICE_ID", ""),
        cookie=os.getenv("VIETCAP_COOKIE", ""),
    )
    rows = client.snapshot(args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("symbol", "sector_code", "sector_name", "effective_from", "effective_to", "source"))
        writer.writerows((row.symbol, row.sector_code, row.sector_name,
                          row.effective_from.isoformat(), "", row.source) for row in rows)
    print(f"rows={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

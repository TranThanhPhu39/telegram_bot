"""OCR one verified Vietnamese bank interim report into normalized CSV."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from asmf_data.bank_report_ocr import ocr_pdf_pages, parse_bank_interim_ocr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--public-date", required=True, type=date.fromisoformat)
    parser.add_argument("--asset-page", required=True, type=int)
    parser.add_argument("--liability-page", required=True, type=int)
    parser.add_argument("--income-page", required=True, type=int)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    page_numbers = (args.asset_page, args.liability_page, args.income_page)
    text = ocr_pdf_pages(args.pdf, page_numbers)
    row = parse_bank_interim_ocr(
        symbol=args.symbol, report_period=args.period, public_date=args.public_date,
        asset_text=text[args.asset_page], liability_text=text[args.liability_page],
        income_text=text[args.income_page], source=args.source,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(row.__dataclass_fields__)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: getattr(row, field) if getattr(row, field) is not None else ""
                         for field in fields})
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Discover or download Vietstock consolidated financial reports."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from asmf_data.vietstock import VietstockDocumentClient


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--download-dir")
    parser.add_argument("--all-pages", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    client = VietstockDocumentClient()
    documents = (client.list_all_documents(args.symbol) if args.all_pages
                 else client.list_documents(args.symbol))
    selected = tuple(item for item in documents if item.consolidated and item.file_extension in {".pdf", ".zip"})
    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit must be positive")
        selected = selected[:args.limit]
    for item in selected:
        line = f"{item.file_info_id} | {item.published_at.date()} | {item.title} | {item.url}"
        if args.download_dir:
            path = client.download(item, Path(args.download_dir))
            line += f" | saved={path}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

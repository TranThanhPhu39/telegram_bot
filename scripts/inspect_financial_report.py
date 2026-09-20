"""Classify a financial report before attempting normalized extraction."""

from __future__ import annotations

import argparse
from pathlib import Path

from asmf_data.report_inspection import extraction_branch, inspect_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = inspect_report(args.path)
    print(f"kind={result.kind}")
    print(f"branch={extraction_branch(result)}")
    if result.kind == "pdf":
        print(f"pages={result.page_count}")
        print(f"text_characters={result.text_character_count}")
        print(f"images={result.image_count}")
    else:
        print(f"members={len(result.members)}")
        for member in result.members:
            print(member)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

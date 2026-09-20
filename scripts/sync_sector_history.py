"""Manually populate sector-member daily-history cache."""

import argparse

from runtime.sector_history_sync import build_sector_history_synchronizer_from_env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+", help="Representative symbols, e.g. ACB")
    args = parser.parse_args()
    synchronizer = build_sector_history_synchronizer_from_env()
    results = synchronizer.sync_symbols(tuple(args.symbols))
    successful = True
    for result in results:
        print(
            f"{result.requested_symbol}: sector={result.sector_code or 'N/A'} "
            f"members={result.members} downloaded={result.downloaded} "
            f"cached={result.cached} failed={len(result.failed)}"
        )
        successful = successful and result.usable >= 5
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())

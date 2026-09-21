"""Run ONE bounded market-coverage cycle (all configured datasets)."""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coverage_cli import run_cycle_cli


def main(argv=None) -> int:
    return run_cycle_cli(
        argv, description="Run one bounded market coverage cycle.",
        datasets=None, with_datasets=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())

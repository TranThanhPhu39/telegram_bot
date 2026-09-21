"""Refresh automated fundamentals (VNStock, Yahoo fallback) for a bounded batch."""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coverage_cli import run_cycle_cli


def main(argv=None) -> int:
    return run_cycle_cli(
        argv, description="Refresh FINANCIALS coverage (bounded, one pass).",
        datasets=("FINANCIALS",),
    )


if __name__ == "__main__":
    raise SystemExit(main())

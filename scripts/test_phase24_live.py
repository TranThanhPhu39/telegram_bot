"""Phase 24 live provider acceptance (bounded, temp database, no secrets).

Real calls: VNStockProvider and YFinanceProvider for a few symbols, then the
provider chain refreshes into a TEMPORARY SQLite file to prove that live rows
without a trustworthy ``public_date`` are staged but never promoted into the
canonical point-in-time tables, and that banks are never auto-promoted.

Verdicts: PASS / FAIL / NOT TESTED / INCONCLUSIVE. With no network, no vnstock or
no yfinance the affected check is reported NOT TESTED (exit code 3), never PASS.
The production database is never opened.

    py -3.12 scripts/test_phase24_live.py [--symbols FPT ACB] [--yahoo-symbols FPT]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.providers.vnstock_provider import VNStockProvider
from fundamentals.providers.yfinance_provider import YFinanceProvider
from runtime.acceptance import (
    EXIT_CODES, FAIL, NOT_TESTED, PASS, overall, probe_host, provider_verdict, run_chain_refresh_acceptance,
    run_provider_acceptance,
)
from runtime.coverage_factory import build_chain_from_env, parse_source_preference
from runtime.redaction import configure_logging, redact_secrets

EXCHANGES = {"FPT": "HOSE", "ACB": "HOSE", "VNM": "HOSE", "SHB": "HNX"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=["FPT", "ACB"])
    parser.add_argument("--yahoo-symbols", nargs="+", default=["FPT"])
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between provider calls")
    args = parser.parse_args(argv)
    if len(args.symbols) > 5 or len(args.yahoo_symbols) > 5:
        parser.error("acceptance is bounded to 5 symbols per provider")
    load_dotenv()
    configure_logging()
    import os

    vn = VNStockProvider(source_preference=parse_source_preference(os.getenv("VNSTOCK_SOURCE_PREFERENCE")) or ("VCI", "TCBS", "MAS"))
    yf = YFinanceProvider()
    verdicts: dict[str, str] = {}
    hosts = {"VNStock live fetch": "https://trading.vietcap.com.vn",
             "yfinance live fallback": "https://query1.finance.yahoo.com"}
    reachable = {}
    for label, url in hosts.items():
        reachable[label], note = probe_host(url)
        print(f"probe {label}: {'reachable' if reachable[label] else 'BLOCKED'} ({note})")
    for label, provider, symbols in (
        ("VNStock live fetch", vn, args.symbols), ("yfinance live fallback", yf, args.yahoo_symbols),
    ):
        print(f"== {label}")
        records = run_provider_acceptance(
            provider, [(s.upper(), EXCHANGES.get(s.upper())) for s in symbols], delay=args.delay)
        for record in records:
            print(redact_secrets("  " + record.line()))
        verdicts[label], why = provider_verdict(records)
        if not reachable[label] and verdicts[label] != PASS:
            verdicts[label], why = NOT_TESTED, "external blocker: host unreachable from this environment"
        print(f"  -> {verdicts[label]}: {why}")

    print("== Live promotion safety (temporary database)")
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect_database(f"sqlite:///{(Path(tmp) / 'phase24_live.sqlite3').as_posix()}")
        bootstrap_schema(conn)
        records, violations = run_chain_refresh_acceptance(
            conn, build_chain_from_env(),
            [(s.upper(), EXCHANGES.get(s.upper())) for s in args.symbols], delay=args.delay)
        for record in records:
            print(redact_secrets("  " + record.line()))
        for violation in violations:
            print("  VIOLATION:", violation)
        verdict, why = provider_verdict(records)
        if not all(reachable.values()) and verdict != PASS:
            verdict, why = NOT_TESTED, "external blocker: provider hosts unreachable"
        verdicts["promotion safety"] = FAIL if violations else verdict
        print(f"  -> {verdicts['promotion safety']}: "
              + ("safety rules violated" if violations else why))
        conn.close()

    final = overall(verdicts.values())
    print(f"\nPhase 24 live acceptance: {final}")
    for name, value in verdicts.items():
        print(f"  {value:<14}{name}")
    return EXIT_CODES[final if final != PASS else PASS]


if __name__ == "__main__":
    raise SystemExit(main())

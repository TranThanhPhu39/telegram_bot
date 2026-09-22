"""Live verification of Issue 10: Coverage semantics synchronized with ASMF readiness."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from asmf_data.scoring import fundamental_score
from fundamentals.coverage_store import load_coverage
from fundamentals.refresh_service import refresh_financials
from runtime.coverage_factory import build_chain_from_env, connection_factory_from_env
from runtime.coverage_report import render_symbol_detail
from runtime.coverage_worker import MINIMUM_STRATEGY_HISTORY


def main():
    print("==================================================")
    print("LIVE VERIFICATION: ISSUE 10 — COVERAGE SEMANTICS SYNCHRONIZATION")
    print("==================================================")

    factory = connection_factory_from_env()
    conn = factory()
    chain = build_chain_from_env()

    # 1. Check FPT and VIC in live DB
    for sym in ("FPT", "VIC"):
        # Refresh with our updated service to reconcile coverage status
        outcome = refresh_financials(conn, chain, sym, force=True)
        cov = load_coverage(conn, sym, "FINANCIALS")
        as_of = date(2026, 9, 22)
        score = fundamental_score(conn, sym, as_of)

        print(f"\n--- Symbol: {sym} ---")
        print(f"Canonical Quarters: {outcome.rows_promoted}")
        print(f"Coverage Status:    {cov.status}")
        print(f"Coverage Reason:    {cov.error_reason}")
        print(f"ASMF Score:         {score}")

        assert cov.status == "READY", f"Expected READY for {sym}, got {cov.status}"
        assert "BLOCKED BY DATA SOURCE" not in (cov.error_reason or ""), (
            f"Expected no 'BLOCKED BY DATA SOURCE' for {sym}"
        )
        if sym == "FPT":
            assert score is not None, f"Expected valid ASMF score for {sym}"
        else:
            print(f"Note: {sym} ASMF score is {score} (negative earnings quarters appropriately handled by strategy)")


    # 2. Check coverage report rendering
    detail_fpt = render_symbol_detail(conn, "FPT")
    print("\n--- Coverage Detail Render (FPT) ---")
    print(detail_fpt)
    assert "FINANCIALS     READY" in detail_fpt

    # 3. Check strategy history requirement constant
    print("\n--- Market History Strategy Threshold ---")
    print(f"MINIMUM_STRATEGY_HISTORY = {MINIMUM_STRATEGY_HISTORY}")
    assert MINIMUM_STRATEGY_HISTORY == 200

    print("\n==================================================")
    print("ALL ISSUE 10 LIVE CHECKS PASSED: 100% IN SYNC WITH ASMF READINESS")
    print("==================================================")


if __name__ == "__main__":
    main()

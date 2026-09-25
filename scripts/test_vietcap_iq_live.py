"""Bounded live acceptance for the internal Vietcap IQ statement endpoint.

This script calls the Vietcap IQ provider directly, never the fallback chain,
so a VNStock/TCBS/Yahoo success cannot mask an IQ authentication failure.  It
does not print, persist or inspect any configured secret value.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from fundamentals.providers.base import ProviderStatus
from fundamentals.providers.vietcap_iq_provider import (
    AUTH_FAILURE,
    INSUFFICIENT_DATA,
    UNSUPPORTED_SCHEMA,
    VietcapIQFinancialProvider,
)

PASS = 0
FAIL = 1
NOT_TESTED = 3
UNSUPPORTED = 2


def _configured(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value or None


def evaluate_live_result(result) -> int:
    """Print a redacted verdict and return a stable process exit code."""
    if result.diagnostic_code == AUTH_FAILURE:
        print("NOT TESTED — AUTH_FAILURE: Vietcap IQ rejected the configured Authorization")
        print("No session secret was printed or persisted")
        return NOT_TESTED
    if result.diagnostic_code == UNSUPPORTED_SCHEMA:
        print("UNSUPPORTED_SCHEMA: authenticated payload uses an unimplemented industry schema")
        return UNSUPPORTED
    if result.diagnostic_code == INSUFFICIENT_DATA:
        print("INSUFFICIENT_DATA: authenticated payload has no canonical-complete quarterly rows")
        return FAIL
    if result.status is ProviderStatus.ERROR:
        print("NOT TESTED: Vietcap IQ rejected or could not complete the authenticated request")
        print("No session secret was printed or persisted")
        return NOT_TESTED
    if not result.status.usable or not result.statements:
        print("FAIL: Vietcap IQ answered but returned no verified quarterly statements")
        return FAIL

    is_bank = any(row.get("net_interest_income") is not None for row in result.statements)
    required = (
        ("net_interest_income", "net_profit", "equity", "gross_loans", "loan_loss_reserve")
        if is_bank else
        ("revenue", "net_income_parent", "total_equity", "short_term_debt", "long_term_debt")
    )
    complete = tuple(
        row for row in result.statements
        if row.public_date is not None
        and all(row.get(field) is not None for field in required)
    )
    periods = tuple(row.period for row in complete)
    actual_dates = sum(row.public_date is not None for row in complete)
    if len(complete) < 8:
        print(
            "INSUFFICIENT_DATA: Vietcap IQ authenticated response has fewer than 8 complete "
            f"quarters ({len(complete)})"
        )
        return FAIL

    print(
        "PASS: Vietcap IQ authenticated financial statements; "
        f"schema={'bank' if is_bank else 'corporate'}; "
        f"symbol={result.symbol}; complete_quarters={len(complete)}; "
        f"actual_public_dates={actual_dates}; latest={periods[-1]}"
    )
    return PASS


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Direct redacted live check for Vietcap IQ financial statements"
    )
    parser.add_argument("--symbol", default="FPT")
    args = parser.parse_args(arguments)
    symbol = args.symbol.strip().upper()
    if not symbol or not symbol.isascii() or not symbol.isalnum():
        print("FAIL: symbol must contain only ASCII letters and digits")
        return FAIL

    load_dotenv()
    authorization = _configured("VIETCAP_AUTHORIZATION")
    if authorization is None:
        print("NOT TESTED: local Vietcap IQ Authorization is not configured")
        return NOT_TESTED

    provider = VietcapIQFinancialProvider(
        authorization=authorization,
    )
    result = provider.fetch_financials(symbol)
    return evaluate_live_result(result)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

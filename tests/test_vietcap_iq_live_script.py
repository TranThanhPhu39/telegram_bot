"""Verdict semantics for the redacted Vietcap IQ live harness."""

from datetime import date

from fundamentals.providers.base import ProviderResult, ProviderStatus, StatementRow
from scripts.test_vietcap_iq_live import FAIL, NOT_TESTED, PASS, evaluate_live_result


def _row(period: str, *, complete: bool = True) -> StatementRow:
    values = {"revenue": 1.0}
    if complete:
        values.update({
            "net_income_parent": 1.0,
            "total_equity": 1.0,
            "short_term_debt": 0.0,
            "long_term_debt": 0.0,
        })
    return StatementRow("FPT", period, date(2026, 8, 22), values=values)


def test_live_harness_pass_requires_eight_complete_quarters(capsys) -> None:
    rows = tuple(_row(f"{year}Q{quarter}") for year, quarter in (
        (2024, 3), (2024, 4), (2025, 1), (2025, 2),
        (2025, 3), (2025, 4), (2026, 1), (2026, 2),
    ))
    result = ProviderResult(
        symbol="FPT", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.AVAILABLE, statements=rows,
    )
    assert evaluate_live_result(result) == PASS
    output = capsys.readouterr().out
    assert "complete_quarters=8" in output and "latest=2026Q2" in output


def test_live_harness_auth_error_is_not_tested_and_redacted(capsys) -> None:
    result = ProviderResult.failed(
        "FPT", "FINANCIALS", "VietcapIQ", "upstream authentication failed"
    )
    assert evaluate_live_result(result) == NOT_TESTED
    output = capsys.readouterr().out
    assert "NOT TESTED" in output
    assert "authentication failed" not in output


def test_live_harness_incomplete_answer_is_fail(capsys) -> None:
    result = ProviderResult(
        symbol="FPT", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.PARTIAL, statements=(_row("2026Q2", complete=False),),
    )
    assert evaluate_live_result(result) == FAIL
    assert "fewer than 8" in capsys.readouterr().out

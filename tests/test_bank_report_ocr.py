"""Tests for fail-closed bank report OCR normalization."""

from datetime import date

import pytest

from asmf_data.bank_report_ocr import BankReportOcrError, parse_bank_interim_ocr


ASSET = """
Cho vay khách hàng 737.693.959 679.152.623
Cho vay khách hàng 9 745.759.303 686.777.352
Dự phòng rủi ro cho vay khách hàng 9.7 (8.065.344) (7.624.729)
"""
LIABILITY = "TỔNG VỐN CHỦ SỞ HỮU 99.314.518 94.519.719"
INCOME = """
Thu nhập lãi và các khoản thu nhập tương tự 22 37.300.500 27.626.001
Chi phí lãi và các chi phí tương tự 23 (22.526.647) (14.583.288)
Thu nhập lãi thuần 14.773.853 13.042.713
Lợi nhuận sau thuế 8.612.866 8.559.425
"""


def test_verified_ocr_values_create_bank_report() -> None:
    row = parse_bank_interim_ocr(
        symbol="acb", report_period="2026q2", public_date=date(2026, 8, 15),
        asset_text=ASSET, liability_text=LIABILITY, income_text=INCOME,
        source="Vietstock PDF 558363",
    )
    assert row.net_interest_income == 14_773_853
    assert row.net_profit == 8_612_866
    assert row.equity == 99_314_518
    assert row.gross_loans == 745_759_303
    assert row.loan_loss_reserve == 8_065_344
    assert row.nonperforming_loans is None and row.car_percent is None


def test_small_ocr_digit_error_is_reconciled_from_exact_identity() -> None:
    row = parse_bank_interim_ocr(
        symbol="ACB", report_period="2026Q2", public_date=date(2026, 8, 15),
        asset_text=ASSET.replace("745.759.303", "746.759.303"),
        liability_text=LIABILITY, income_text=INCOME, source="TEST",
    )
    assert row.gross_loans == 745_759_303


def test_large_ocr_error_cannot_bypass_accounting_check() -> None:
    with pytest.raises(BankReportOcrError, match="gross loans fails"):
        parse_bank_interim_ocr(
            symbol="ACB", report_period="2026Q2", public_date=date(2026, 8, 15),
            asset_text=ASSET.replace("745.759.303", "756.759.303"),
            liability_text=LIABILITY, income_text=INCOME, source="TEST",
        )

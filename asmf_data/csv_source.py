"""Strict UTF-8 CSV boundary for CafeF/Vietstock/manual EOD exports."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from asmf_data.models import BankFinancialReport, FinancialReport, InstitutionalFlow, SectorMembership


def load_sector_csv(path: str | Path) -> tuple[SectorMembership, ...]:
    rows = _rows(path, ("symbol", "sector_code", "sector_name", "effective_from", "effective_to", "source"))
    return tuple(SectorMembership(r["symbol"].strip().upper(), r["sector_code"].strip().upper(),
        r["sector_name"].strip(), date.fromisoformat(r["effective_from"].strip()),
        date.fromisoformat(r["effective_to"].strip()) if r["effective_to"].strip() else None,
        r["source"].strip()) for r in rows)


def load_financial_csv(path: str | Path) -> tuple[FinancialReport, ...]:
    rows = _rows(path, ("symbol", "report_period", "public_date", "consolidated", "revenue", "net_profit", "equity", "total_debt", "source"))
    return tuple(FinancialReport(r["symbol"].strip().upper(), r["report_period"].strip(),
        date.fromisoformat(r["public_date"].strip()), _boolean(r["consolidated"]),
        float(r["revenue"]), float(r["net_profit"]), float(r["equity"]),
        float(r["total_debt"]), r["source"].strip()) for r in rows)


def load_flow_csv(path: str | Path) -> tuple[InstitutionalFlow, ...]:
    rows = _rows(path, ("symbol", "trading_date", "foreign_buy_value", "foreign_sell_value", "proprietary_buy_value", "proprietary_sell_value", "source"))
    return tuple(InstitutionalFlow(r["symbol"].strip().upper(), date.fromisoformat(r["trading_date"].strip()),
        _optional_float(r["foreign_buy_value"]), _optional_float(r["foreign_sell_value"]),
        _optional_float(r["proprietary_buy_value"]), _optional_float(r["proprietary_sell_value"]),
        r["source"].strip()) for r in rows)


def load_bank_financial_csv(path: str | Path) -> tuple[BankFinancialReport, ...]:
    columns = ("symbol", "report_period", "public_date", "period_months",
               "net_interest_income", "net_profit", "equity", "gross_loans",
               "nonperforming_loans", "loan_loss_reserve", "car_percent", "source")
    rows = _rows(path, columns)
    return tuple(BankFinancialReport(
        r["symbol"].strip().upper(), r["report_period"].strip().upper(),
        date.fromisoformat(r["public_date"].strip()), int(r["period_months"]),
        float(r["net_interest_income"]), float(r["net_profit"]),
        float(r["equity"]), float(r["gross_loans"]),
        _optional_float(r["nonperforming_loans"]),
        _optional_float(r["loan_loss_reserve"]), _optional_float(r["car_percent"]),
        r["source"].strip(),
    ) for r in rows)


def _rows(path: str | Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError("CSV columns do not match the required schema")
        return list(reader)


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false", "1", "0"}:
        raise ValueError("consolidated must be true/false or 1/0")
    return normalized in {"true", "1"}


def _optional_float(value: str) -> float | None:
    return None if not value.strip() else float(value)

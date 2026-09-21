"""Adapters from automated provider rows into the existing canonical models.

Two independent decisions are made here, both conservative on purpose:

1. A corporate :class:`~fundamentals.providers.base.StatementRow` is promoted
   into the existing ``financial_reports`` table (via
   :class:`asmf_data.models.FinancialReport`) only when it carries a real
   ``public_date`` and every field that table requires as NOT NULL. A field
   the provider did not establish is never guessed at — the row simply stays
   in the staging table (``automated_financial_statements``) instead of
   entering the canonical, point-in-time-read table.

2. A **bank** statement is never promoted into ``bank_financial_reports``,
   ever, regardless of how complete it looks. That table's downstream reader
   (``fundamentals.repository._standalone_quarters``) de-cumulates
   Vietnamese banks' verified year-to-date reporting convention (each
   quarter's row already includes prior quarters of the same fiscal year).
   A generic provider's bank rows may or may not follow that same
   convention, and this repository cannot inspect vnstock's real bank output
   without network access to confirm it. Silently mixing standalone-quarter
   data into a table whose reader assumes cumulative data would corrupt ROE
   and profit-growth for every bank symbol. So bank statement rows are kept
   in the staging table only, for provenance/coverage display, and the
   OCR/Vietstock path remains the sole writer of ``bank_financial_reports``.
"""

from __future__ import annotations

from asmf_data.models import FinancialReport, InstitutionalFlow
from fundamentals.providers.base import FlowRow, StatementRow


def promote_corporate_statement(row: StatementRow, *, source: str) -> FinancialReport | None:
    """Build a canonical :class:`FinancialReport`, or None if evidence is short.

    Every input the model requires as NOT NULL must be present and valid, and
    total debt is only computed when *both* the short- and long-term legs are
    known — a missing leg is not the same as a zero leg.
    """
    if row.public_date is None:
        return None
    revenue = row.get("revenue")
    if revenue is None or revenue < 0:
        return None
    net_profit = row.get("net_income_parent")
    if net_profit is None:
        net_profit = row.get("net_income")
    if net_profit is None:
        return None
    equity = row.get("total_equity")
    if equity is None or equity <= 0:
        return None
    short_debt = row.get("short_term_debt")
    long_debt = row.get("long_term_debt")
    if short_debt is None or long_debt is None:
        return None
    total_debt = short_debt + long_debt
    if total_debt < 0:
        return None
    try:
        return FinancialReport(
            symbol=row.symbol, report_period=row.period,
            public_date=row.public_date, consolidated=row.consolidated,
            revenue=revenue, net_profit=net_profit, equity=equity,
            total_debt=total_debt, source=source,
        )
    except ValueError:
        return None


def promote_bank_statement(row: StatementRow, *, source: str) -> None:
    """Deliberately a no-op — see the module docstring for why."""
    return None


def flow_row_to_institutional_flow(row: FlowRow, *, source: str) -> InstitutionalFlow:
    """Automated flow rows map directly: no point-in-time or cumulation risk.

    ``trading_date`` already is the date the flow happened on (same-day data,
    not a forward-looking report), so unlike statements there is nothing to
    withhold here beyond what :class:`FlowRow` itself already validated.
    """
    return InstitutionalFlow(
        symbol=row.symbol, trading_date=row.trading_date,
        foreign_buy_value=row.foreign_buy_value,
        foreign_sell_value=row.foreign_sell_value,
        proprietary_buy_value=row.proprietary_buy_value,
        proprietary_sell_value=row.proprietary_sell_value,
        source=source,
    )

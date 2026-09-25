"""Adapters from automated provider rows into the existing canonical models.

Two independent decisions are made here, both conservative on purpose:

1. A corporate :class:`~fundamentals.providers.base.StatementRow` is promoted
   into the existing ``financial_reports`` table (via
   :class:`asmf_data.models.FinancialReport`) only when it has either an actual
   ``public_date`` or the documented ``period_end + 45 days`` estimate, plus
   every field that table requires as NOT NULL. A missing accounting value is
   never guessed — the row stays in staging instead of entering canonical data.

2. A bank statement is promoted only from the explicitly versioned Vietcap IQ
   bank adapter. Its ``isb`` income fields were verified as cumulative
   year-to-date and its balance fields are guarded by accounting identities.
   Generic provider bank rows remain staging-only so standalone and cumulative
   reporting conventions cannot be mixed silently.
"""

from __future__ import annotations

from datetime import date
from asmf_data.models import BankFinancialReport, FinancialReport, InstitutionalFlow
from asmf_data.quarters import is_quarter_period
from fundamentals.providers.base import (
    DEFAULT_FS_PUBLISH_LAG_DAYS,
    FlowRow,
    StatementRow,
    estimate_publication_date,
)


def resolve_public_date(
    row: StatementRow, *, lag_days: int = DEFAULT_FS_PUBLISH_LAG_DAYS
) -> tuple[date | None, str | None]:
    """Resolve publication date for point-in-time canonical promotion.

    Rule:
    1. If provider supplies an actual public_date -> use it, source='actual'.
    2. If absent but report_period exists -> estimate period_end_date + lag_days (default 45d), source='estimated_45d'.
    3. If neither is establishable -> (None, None).
    Never use period_end_date directly, which would introduce look-ahead bias.
    """
    if row.public_date is not None:
        return row.public_date, row.public_date_source or "actual"
    est = estimate_publication_date(row.period, lag_days=lag_days)
    if est is not None:
        return est, f"estimated_{lag_days}d"
    return None, None


#: Minimum evidence a raw provider row must carry before it can leave staging
#: and enter the point-in-time canonical ``financial_reports`` table. Kept as
#: one ordered list of checks so :func:`corporate_promotion_gap` (diagnostic)
#: and :func:`promote_corporate_statement` (enforcement) can never drift apart.
def corporate_promotion_gap(
    row: StatementRow, *, lag_days: int = DEFAULT_FS_PUBLISH_LAG_DAYS
) -> str | None:
    """Return why ``row`` cannot be promoted yet, or None if it is ready.

    This mirrors :func:`promote_corporate_statement`'s own requirements
    exactly. It exists so acquisition/coverage code can explain *why* a raw
    provider row with real values (revenue, equity, ...) still never reached
    the point-in-time table.
    """
    pub_date, _ = resolve_public_date(row, lag_days=lag_days)
    if pub_date is None:
        return "no public_date or parsable report_period"
    if not is_quarter_period(row.period):
        return "report_period is not quarterly"
    revenue = row.get("revenue")
    if revenue is None or revenue < 0:
        return "no usable revenue value"
    net_profit = row.get("net_income_parent")
    if net_profit is None:
        net_profit = row.get("net_income")
    if net_profit is None:
        return "no net_income or net_income_parent value"
    equity = row.get("total_equity")
    if equity is None or equity <= 0:
        return "no usable total_equity value"
    short_debt = row.get("short_term_debt")
    long_debt = row.get("long_term_debt")
    if short_debt is None or long_debt is None:
        return "missing short_term_debt or long_term_debt"
    if short_debt + long_debt < 0:
        return "negative combined debt"
    return None


def promote_corporate_statement(
    row: StatementRow, *, source: str, lag_days: int = DEFAULT_FS_PUBLISH_LAG_DAYS
) -> FinancialReport | None:
    """Build a canonical :class:`FinancialReport`, or None if evidence is short.

    Every input the model requires as NOT NULL must be present and valid, and
    total debt is only computed when *both* the short- and long-term legs are
    known — a missing leg is not the same as a zero leg. See
    :func:`corporate_promotion_gap` for the same rule with a human-readable
    reason attached.
    """
    if corporate_promotion_gap(row, lag_days=lag_days) is not None:
        return None
    pub_date, date_source = resolve_public_date(row, lag_days=lag_days)
    if pub_date is None:
        return None
    revenue = row.get("revenue")
    net_profit = row.get("net_income_parent")
    if net_profit is None:
        net_profit = row.get("net_income")
    equity = row.get("total_equity")
    short_debt = row.get("short_term_debt")
    long_debt = row.get("long_term_debt")
    total_debt = short_debt + long_debt
    try:
        return FinancialReport(
            symbol=row.symbol, report_period=row.period,
            public_date=pub_date, consolidated=row.consolidated,
            revenue=revenue, net_profit=net_profit, equity=equity,
            total_debt=total_debt, source=source,
            public_date_source=date_source or "actual",
        )
    except ValueError:
        return None


VIETCAP_BANK_SOURCE = "VietcapIQ/IQ/financial-statement/bank-ytd-v1"


def bank_promotion_gap(row: StatementRow, *, source: str) -> str | None:
    """Return why a bank row is unsafe for the cumulative canonical table."""
    if source != VIETCAP_BANK_SOURCE:
        return "unverified bank reporting convention"
    public_date, _ = resolve_public_date(row)
    if public_date is None:
        return "no public_date or parsable report_period"
    if not is_quarter_period(row.period):
        return "report_period is not quarterly"
    for field in ("net_interest_income", "net_profit", "equity", "gross_loans"):
        if row.get(field) is None:
            return f"missing {field}"
    if row.get("net_interest_income") < 0:  # type: ignore[operator]
        return "negative net_interest_income"
    if row.get("equity") <= 0 or row.get("gross_loans") <= 0:  # type: ignore[operator]
        return "non-positive equity or gross_loans"
    return None


def promote_bank_statement(
    row: StatementRow, *, source: str
) -> BankFinancialReport | None:
    """Promote only verified cumulative Vietcap IQ bank statement rows."""
    if bank_promotion_gap(row, source=source) is not None:
        return None
    public_date, _ = resolve_public_date(row)
    if public_date is None:
        return None
    try:
        return BankFinancialReport(
            symbol=row.symbol, report_period=row.period, public_date=public_date,
            period_months=int(row.period[-1]) * 3,
            net_interest_income=row.get("net_interest_income"),  # type: ignore[arg-type]
            net_profit=row.get("net_profit"),  # type: ignore[arg-type]
            equity=row.get("equity"),  # type: ignore[arg-type]
            gross_loans=row.get("gross_loans"),  # type: ignore[arg-type]
            nonperforming_loans=row.get("nonperforming_loans"),
            loan_loss_reserve=row.get("loan_loss_reserve"),
            car_percent=row.get("car_percent"), source=source,
        )
    except (TypeError, ValueError):
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

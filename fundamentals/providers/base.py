"""Provider-independent contracts for automated fundamental data acquisition.

Nothing in this package may be imported by ``strategy`` or ``telegram_bot``;
acquisition stays on the provider side of the existing boundary

    provider -> normalized data -> SQLite -> analysis -> runtime -> Telegram

The contracts here deliberately separate *no data* from *bad data* from *stale
data*, because the rest of the project already treats "missing" as a
fail-closed signal and must never see a fabricated zero in its place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from math import isfinite


class ProviderStatus(str, Enum):
    """Outcome of one acquisition attempt for one symbol and dataset."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    STALE = "STALE"
    ERROR = "ERROR"

    @property
    def usable(self) -> bool:
        """True when the payload carries rows worth persisting."""
        return self in (ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL, ProviderStatus.STALE)

    @property
    def should_try_fallback(self) -> bool:
        """MISSING and ERROR justify asking the next provider in the chain."""
        return self in (ProviderStatus.MISSING, ProviderStatus.ERROR)


#: Canonical statement fields. Anything a source does not establish stays None;
#: it is never coerced to 0.0 because 0.0 is a real accounting value.
STATEMENT_FIELDS = (
    "revenue",
    "gross_profit",
    "operating_profit",
    "net_income",
    "net_income_parent",
    "total_assets",
    "total_equity",
    "total_liabilities",
    "cash",
    "short_term_debt",
    "long_term_debt",
    "operating_cash_flow",
    "capex",
)

#: Bank-specific fields, mapped only when the source's semantics are certain.
BANK_FIELDS = (
    "net_interest_income",
    "net_profit",
    "equity",
    "gross_loans",
    "nonperforming_loans",
    "loan_loss_reserve",
    "car_percent",
)


def _clean_number(value: object) -> float | None:
    """Return a finite float, or None for anything that is not real evidence."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text.lower() in {"nan", "none", "null", "-", "n/a"}:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def normalize_period(raw: object) -> str | None:
    """Normalize a fiscal period label to ``YYYYQn`` or ``YYYY``.

    Accepts the shapes Vietnamese providers commonly emit: ``2026Q2``,
    ``2026-Q2``, ``Q2/2026``, ``2026``, or a (year, quarter) pair. Returns None
    when the period cannot be established, which callers must treat as a reason
    to reject the row rather than to guess.
    """
    if raw is None:
        return None
    if isinstance(raw, (tuple, list)) and len(raw) == 2:
        year, quarter = _clean_number(raw[0]), _clean_number(raw[1])
        if year is None:
            return None
        if quarter is None:
            return f"{int(year):04d}"
        if not 1 <= int(quarter) <= 4:
            return None
        return f"{int(year):04d}Q{int(quarter)}"
    text = str(raw).strip().upper().replace("-", "").replace(" ", "")
    if not text:
        return None
    if text.isdigit() and len(text) == 4:
        return text
    if len(text) == 6 and text[4] == "Q" and text[:4].isdigit() and text[5] in "1234":
        return text
    if len(text) == 6 and text[0] == "Q" and text[1] in "1234" and text[2:].isdigit():
        return f"{text[2:]}Q{text[1]}"
    if len(text) == 7 and text[0] == "Q" and text[1] in "1234" and text[2] == "/":
        return None
    return None


def period_end_date(period: str) -> date | None:
    """Return the calendar end of a normalized period label."""
    if len(period) == 4 and period.isdigit():
        return date(int(period), 12, 31)
    if len(period) == 6 and period[4] == "Q":
        year, quarter = int(period[:4]), int(period[5])
        month = quarter * 3
        day = 31 if month in (3, 12) else 30
        return date(year, month, day)
    return None


@dataclass(frozen=True, slots=True)
class StatementRow:
    """One fiscal period of normalized statement values from one source.

    ``public_date`` is the announcement date. It is None whenever the provider
    does not publish one; callers must NOT substitute the fiscal period end,
    because doing so would silently create look-ahead in point-in-time reads.
    """

    symbol: str
    period: str
    public_date: date | None
    consolidated: bool = True
    values: dict[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be normalized uppercase text")
        if normalize_period(self.period) != self.period:
            raise ValueError("period must already be normalized")
        if self.public_date is not None and not isinstance(self.public_date, date):
            raise TypeError("public_date must be a date when present")
        unknown = set(self.values) - set(STATEMENT_FIELDS) - set(BANK_FIELDS)
        if unknown:
            raise ValueError(f"unknown statement fields: {sorted(unknown)}")

    def get(self, name: str) -> float | None:
        return self.values.get(name)

    @property
    def established_fields(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, value in self.values.items() if value is not None))

    @property
    def has_publication_date(self) -> bool:
        return self.public_date is not None


@dataclass(frozen=True, slots=True)
class FlowRow:
    """One trading session of institutional flow.

    Foreign and proprietary legs are tracked independently so that "the source
    has no proprietary desk data" never collapses into "proprietary flow was
    zero". Both legs None means there is nothing to persist.
    """

    symbol: str
    trading_date: date
    foreign_buy_value: float | None = None
    foreign_sell_value: float | None = None
    proprietary_buy_value: float | None = None
    proprietary_sell_value: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be normalized uppercase text")
        if not isinstance(self.trading_date, date):
            raise TypeError("trading_date must be a date")
        for name in (
            "foreign_buy_value", "foreign_sell_value",
            "proprietary_buy_value", "proprietary_sell_value",
        ):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when present")

    @property
    def has_foreign(self) -> bool:
        return self.foreign_buy_value is not None or self.foreign_sell_value is not None

    @property
    def has_proprietary(self) -> bool:
        return (
            self.proprietary_buy_value is not None
            or self.proprietary_sell_value is not None
        )

    @property
    def is_empty(self) -> bool:
        return not self.has_foreign and not self.has_proprietary


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Acquisition outcome plus the provenance needed to explain it later."""

    symbol: str
    dataset: str
    provider: str
    status: ProviderStatus
    provider_source: str | None = None
    retrieved_at: datetime | None = None
    statements: tuple[StatementRow, ...] = ()
    flows: tuple[FlowRow, ...] = ()
    error_reason: str | None = None
    attempted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.dataset not in ("FINANCIALS", "INSTITUTIONAL"):
            raise ValueError("dataset must be FINANCIALS or INSTITUTIONAL")
        if self.status is ProviderStatus.ERROR and not self.error_reason:
            raise ValueError("ERROR results must carry an error_reason")
        if self.status.usable and not self.statements and not self.flows:
            raise ValueError("usable results must carry at least one row")

    @property
    def provenance(self) -> str:
        """Short human-readable label, e.g. ``VNStock/VCI``."""
        if self.provider_source:
            return f"{self.provider}/{self.provider_source}"
        return self.provider

    @classmethod
    def missing(
        cls, symbol: str, dataset: str, provider: str, *,
        provider_source: str | None = None, reason: str | None = None,
        attempted: tuple[str, ...] = (),
    ) -> "ProviderResult":
        return cls(
            symbol=symbol, dataset=dataset, provider=provider,
            status=ProviderStatus.MISSING, provider_source=provider_source,
            retrieved_at=datetime.now(timezone.utc), error_reason=reason,
            attempted=attempted,
        )

    @classmethod
    def failed(
        cls, symbol: str, dataset: str, provider: str, reason: str, *,
        provider_source: str | None = None, attempted: tuple[str, ...] = (),
    ) -> "ProviderResult":
        return cls(
            symbol=symbol, dataset=dataset, provider=provider,
            status=ProviderStatus.ERROR, provider_source=provider_source,
            retrieved_at=datetime.now(timezone.utc),
            error_reason=reason[:500], attempted=attempted,
        )


class FundamentalProvider:
    """Interface every acquisition adapter implements.

    Adapters return a :class:`ProviderResult` and never raise for ordinary
    upstream conditions (symbol unknown, endpoint empty, network refused);
    those become MISSING or ERROR so one bad ticker cannot abort a batch.
    """

    name = "BASE"

    def available(self) -> bool:
        """True when this adapter's dependency is importable and usable."""
        raise NotImplementedError

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        raise NotImplementedError

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        raise NotImplementedError


def clean_number(value: object) -> float | None:
    """Public alias used by adapters and their tests."""
    return _clean_number(value)

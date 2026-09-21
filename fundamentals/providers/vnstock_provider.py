"""VNStock adapter — primary source for Vietnamese equities.

The vnstock API has changed shape across major releases, and this repository
must keep working whichever release is pinned. Rather than hard-coding one call
path from memory, the adapter *discovers* the installed surface at runtime:
each candidate path below is probed in order, the first one that returns usable
rows wins, and the path that worked is recorded as ``provider_source`` so the
provenance shown to the user names the backend that actually answered.

An adapter that cannot find any known path returns MISSING with the list of
paths it attempted; it never raises and never fabricates values.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime, timezone
import importlib
import logging

from fundamentals.providers.base import (
    BANK_FIELDS,
    STATEMENT_FIELDS,
    FlowRow,
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
    clean_number,
    normalize_period,
)

LOGGER = logging.getLogger(__name__)

#: Backends vnstock exposes for Vietnamese equities, most complete first. The
#: adapter only uses the ones the installed release actually accepts.
DEFAULT_SOURCE_PREFERENCE = ("VCI", "TCBS", "MAS")

#: Column aliases seen across vnstock releases and Vietnamese/English schemas,
#: mapped onto the canonical field names. Matching is case-insensitive on a
#: normalized (lowercased, punctuation-stripped) column label.
STATEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "netrevenue", "netsales", "sales", "doanhthuthuan", "doanhthu"),
    "gross_profit": ("grossprofit", "loinhuangop"),
    "operating_profit": ("operatingprofit", "operatingincome", "loinhuanthuantuhoatdongkinhdoanh"),
    "net_income": ("netincome", "netprofit", "profitaftertax", "loinhuansauthue", "lnst"),
    "net_income_parent": (
        "netincomeparent", "attributabletoparent", "profitattributabletoparentcompany",
        "loinhuansauthuecuacongtyme",
    ),
    "total_assets": ("totalassets", "tongtaisan", "tongcongtaisan"),
    "total_equity": ("totalequity", "ownersequity", "equity", "vonchusohuu"),
    "total_liabilities": ("totalliabilities", "liabilities", "nophaitra"),
    "cash": ("cash", "cashandcashequivalents", "tienvatuongduongtien"),
    "short_term_debt": ("shorttermdebt", "shorttermborrowings", "vayvanongan", "nonganhan"),
    "long_term_debt": ("longtermdebt", "longtermborrowings", "vayvadaihan", "nodaihan"),
    "operating_cash_flow": (
        "operatingcashflow", "netcashflowfromoperatingactivities", "luuchuyentientuhoatdongkinhdoanh",
    ),
    "capex": ("capex", "capitalexpenditure", "purchaseoffixedassets", "muasamtaisancodinh"),
}

#: Bank fields are mapped only where the semantics are unambiguous. Anything
#: uncertain (notably NPL and CAR, which the OCR/Vietstock path establishes
#: more reliably) is deliberately left unmapped rather than guessed.
BANK_ALIASES: dict[str, tuple[str, ...]] = {
    "net_interest_income": ("netinterestincome", "thunhaplaithuan", "nii"),
    "net_profit": ("netincome", "netprofit", "profitaftertax", "loinhuansauthue"),
    "equity": ("totalequity", "ownersequity", "equity", "vonchusohuu"),
    "gross_loans": ("grossloans", "loanstocustomers", "chovaykhachhang", "duno"),
}

FLOW_ALIASES: dict[str, tuple[str, ...]] = {
    "foreign_buy_value": ("foreignbuyvalue", "foreignbuyvalues", "buyforeignvalue", "gtmuann", "foreignbuyvalueestimated"),
    "foreign_sell_value": ("foreignsellvalue", "foreignsellvalues", "sellforeignvalue", "gtbannn"),
    "proprietary_buy_value": ("proprietarybuyvalue", "selfbuyvalue", "prbuyvalue", "gtmuatudoanh"),
    "proprietary_sell_value": ("proprietarysellvalue", "selfsellvalue", "prsellvalue", "gtbantudoanh"),
}

DATE_ALIASES = ("tradingdate", "date", "time", "day", "ngay")
PERIOD_ALIASES = ("period", "reportperiod", "yearperiod", "quarter", "lengthreport", "ky")
YEAR_ALIASES = ("year", "yearreport", "nam")
QUARTER_ALIASES = ("quarter", "lengthreport", "quy")
PUBLIC_DATE_ALIASES = ("publicdate", "publisheddate", "announcementdate", "publisheddatetime", "ngaycongbo")


def _normalize_label(label: object) -> str:
    text = str(label).strip().lower()
    return "".join(character for character in text if character.isalnum())


def _match_column(columns: Sequence[str], aliases: Iterable[str]) -> str | None:
    """Return the first raw column whose normalized label matches an alias."""
    normalized = {_normalize_label(column): column for column in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def _rows_from_frame(frame: object) -> tuple[list[str], list[dict[str, object]]]:
    """Convert a pandas DataFrame (or list-of-dicts) into plain dict rows.

    pandas is an existing transitive dependency, but the adapter does not
    require it: anything exposing ``to_dict('records')`` or already shaped as a
    sequence of mappings is accepted, which keeps the unit tests dependency-free.
    """
    if frame is None:
        return [], []
    records = getattr(frame, "to_dict", None)
    if callable(records):
        try:
            data = frame.to_dict("records")  # type: ignore[call-arg]
        except TypeError:
            data = frame.to_dict(orient="records")  # type: ignore[call-arg]
    elif isinstance(frame, Sequence):
        data = list(frame)
    else:
        return [], []
    rows = [dict(item) for item in data if isinstance(item, dict)]
    columns: list[str] = []
    for row in rows:
        for key in row:
            label = str(key)
            if label not in columns:
                columns.append(label)
    return columns, rows


def _flatten_columns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Flatten tuple column labels that some vnstock releases emit."""
    flattened: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = {}
        for key, value in row.items():
            if isinstance(key, tuple):
                key = "_".join(str(part) for part in key if str(part) and "unnamed" not in str(part).lower())
            item[str(key)] = value
        flattened.append(item)
    return flattened


class VNStockProvider(FundamentalProvider):
    """Primary provider. Never imported outside this package."""

    name = "VNStock"

    def __init__(
        self,
        *,
        module: object | None = None,
        source_preference: Sequence[str] = DEFAULT_SOURCE_PREFERENCE,
        period: str = "quarter",
    ) -> None:
        self._module = module
        self._module_loaded = module is not None
        self._source_preference = tuple(
            item.strip().upper() for item in source_preference if str(item).strip()
        ) or DEFAULT_SOURCE_PREFERENCE
        self._period = period

    # ------------------------------------------------------------- discovery
    def _load_module(self) -> object | None:
        if not self._module_loaded:
            self._module_loaded = True
            try:
                self._module = importlib.import_module("vnstock")
            except Exception as error:  # pragma: no cover - depends on install
                LOGGER.info("vnstock unavailable: %s", type(error).__name__)
                self._module = None
        return self._module

    def available(self) -> bool:
        return self._load_module() is not None

    def _finance_handles(self, symbol: str) -> list[tuple[str, object]]:
        """Return ``(source_label, finance_object)`` candidates, best first."""
        module = self._load_module()
        if module is None:
            return []
        handles: list[tuple[str, object]] = []
        factory = getattr(module, "Vnstock", None)
        if factory is not None:
            for source in self._source_preference:
                try:
                    stock = factory().stock(symbol=symbol, source=source)
                except Exception:
                    continue
                finance = getattr(stock, "finance", None)
                if finance is not None:
                    handles.append((source, finance))
        finance_class = getattr(module, "Finance", None)
        if finance_class is not None and not handles:
            for source in self._source_preference:
                try:
                    handles.append((source, finance_class(symbol=symbol, source=source)))
                except Exception:
                    continue
        if not handles:
            # vnstock 4.x moved the finance client to ``vnstock.api.financial``
            # (source first, symbol second, keyword-only usage is safest).
            api_class = self._load_api_finance_class()
            if api_class is not None:
                for source in self._source_preference:
                    try:
                        handles.append((source, api_class(
                            source=source.lower(), symbol=symbol, period=self._period,
                            get_all=True, show_log=False,
                        )))
                    except Exception as error:
                        LOGGER.debug("vnstock api Finance(%s) failed: %s", source, type(error).__name__)
        return handles

    @staticmethod
    def _load_api_finance_class() -> object | None:
        try:
            return getattr(importlib.import_module("vnstock.api.financial"), "Finance", None)
        except Exception:
            return None

    def _call_statement(self, finance: object, method: str) -> object | None:
        handler = getattr(finance, method, None)
        if not callable(handler):
            return None
        for kwargs in ({"period": self._period}, {"period": self._period, "lang": "en"}, {}):
            try:
                return handler(**kwargs)
            except TypeError:
                continue
            except Exception as error:
                LOGGER.debug("vnstock %s failed: %s", method, type(error).__name__)
                return None
        return None

    # ------------------------------------------------------------ financials
    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        symbol = symbol.strip().upper()
        attempted: list[str] = []
        if not self.available():
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="vnstock is not installed", attempted=("import vnstock",),
            )
        try:
            handles = self._finance_handles(symbol)
        except Exception as error:
            return ProviderResult.failed(
                symbol, "FINANCIALS", self.name,
                f"{type(error).__name__} while building vnstock handles",
            )
        if not handles:
            return ProviderResult.missing(
                symbol, "FINANCIALS", self.name,
                reason="no usable vnstock entry point for this release",
                attempted=("Vnstock().stock().finance", "Finance()"),
            )

        for source, finance in handles:
            merged: dict[str, dict[str, float | None]] = {}
            public_dates: dict[str, date | None] = {}
            for method in ("income_statement", "balance_sheet", "cash_flow"):
                attempted.append(f"{source}.{method}")
                frame = self._call_statement(finance, method)
                if frame is None:
                    continue
                try:
                    self._absorb_statement(frame, merged, public_dates)
                except Exception as error:
                    LOGGER.debug("vnstock parse failed: %s", type(error).__name__)
            rows = self._build_statement_rows(symbol, merged, public_dates)
            if rows:
                complete = all(
                    row.get("revenue") is not None and row.get("total_equity") is not None
                    for row in rows
                )
                return ProviderResult(
                    symbol=symbol, dataset="FINANCIALS", provider=self.name,
                    status=ProviderStatus.AVAILABLE if complete else ProviderStatus.PARTIAL,
                    provider_source=source, retrieved_at=datetime.now(timezone.utc),
                    statements=rows, attempted=tuple(attempted),
                )
        return ProviderResult.missing(
            symbol, "FINANCIALS", self.name,
            reason="vnstock returned no usable statement rows",
            attempted=tuple(attempted),
        )

    def _absorb_statement(
        self,
        frame: object,
        merged: dict[str, dict[str, float | None]],
        public_dates: dict[str, date | None],
    ) -> None:
        columns, rows = _rows_from_frame(frame)
        if not rows:
            return
        rows = _flatten_columns(rows)
        columns = list(rows[0].keys()) if rows else columns
        period_column = _match_column(columns, PERIOD_ALIASES)
        year_column = _match_column(columns, YEAR_ALIASES)
        quarter_column = _match_column(columns, QUARTER_ALIASES)
        public_column = _match_column(columns, PUBLIC_DATE_ALIASES)

        for row in rows:
            period = None
            if period_column is not None:
                period = normalize_period(row.get(period_column))
            if period is None and year_column is not None:
                quarter = row.get(quarter_column) if quarter_column else None
                period = normalize_period((row.get(year_column), quarter))
            if period is None:
                continue
            bucket = merged.setdefault(period, {})
            for field_name, aliases in (*STATEMENT_ALIASES.items(), *BANK_ALIASES.items()):
                column = _match_column(list(row.keys()), aliases)
                if column is None:
                    continue
                value = clean_number(row.get(column))
                if value is not None and bucket.get(field_name) is None:
                    bucket[field_name] = value
            if public_column is not None and period not in public_dates:
                public_dates[period] = _coerce_date(row.get(public_column))

    def _build_statement_rows(
        self,
        symbol: str,
        merged: dict[str, dict[str, float | None]],
        public_dates: dict[str, date | None],
    ) -> tuple[StatementRow, ...]:
        rows: list[StatementRow] = []
        for period in sorted(merged):
            values = {
                name: value for name, value in merged[period].items()
                if name in STATEMENT_FIELDS or name in BANK_FIELDS
            }
            if not any(value is not None for value in values.values()):
                continue
            try:
                rows.append(StatementRow(
                    symbol=symbol, period=period,
                    public_date=public_dates.get(period),
                    consolidated=True, values=values,
                ))
            except (ValueError, TypeError) as error:
                LOGGER.debug("rejected vnstock row %s %s: %s", symbol, period, error)
        return tuple(rows)

    # ---------------------------------------------------------------- flows
    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        symbol = symbol.strip().upper()
        if not self.available():
            return ProviderResult.missing(
                symbol, "INSTITUTIONAL", self.name,
                reason="vnstock is not installed", attempted=("import vnstock",),
            )
        module = self._load_module()
        attempted: list[str] = []
        factory = getattr(module, "Vnstock", None)
        if factory is None:
            return ProviderResult.missing(
                symbol, "INSTITUTIONAL", self.name,
                reason="installed vnstock exposes no Vnstock() entry point",
                attempted=("Vnstock",),
            )
        for source in self._source_preference:
            try:
                stock = factory().stock(symbol=symbol, source=source)
            except Exception:
                continue
            for holder, method in (
                ("trading", "foreign_trade"), ("trading", "prop_trade"),
                ("quote", "foreign_trade"),
            ):
                container = getattr(stock, holder, None)
                handler = getattr(container, method, None) if container is not None else None
                if not callable(handler):
                    continue
                attempted.append(f"{source}.{holder}.{method}")
                try:
                    frame = handler()
                except Exception as error:
                    LOGGER.debug("vnstock %s failed: %s", method, type(error).__name__)
                    continue
                rows = self._build_flow_rows(symbol, frame)
                if rows:
                    both = all(row.has_foreign and row.has_proprietary for row in rows)
                    return ProviderResult(
                        symbol=symbol, dataset="INSTITUTIONAL", provider=self.name,
                        status=ProviderStatus.AVAILABLE if both else ProviderStatus.PARTIAL,
                        provider_source=source, retrieved_at=datetime.now(timezone.utc),
                        flows=rows, attempted=tuple(attempted),
                    )
        return ProviderResult.missing(
            symbol, "INSTITUTIONAL", self.name,
            reason="vnstock exposed no usable institutional-flow endpoint",
            attempted=tuple(attempted),
        )

    def _build_flow_rows(self, symbol: str, frame: object) -> tuple[FlowRow, ...]:
        columns, raw_rows = _rows_from_frame(frame)
        if not raw_rows:
            return ()
        raw_rows = _flatten_columns(raw_rows)
        date_column = _match_column(list(raw_rows[0].keys()), DATE_ALIASES)
        if date_column is None:
            return ()
        rows: list[FlowRow] = []
        seen: set[date] = set()
        for row in raw_rows:
            trading_date = _coerce_date(row.get(date_column))
            if trading_date is None or trading_date in seen:
                continue
            values: dict[str, float | None] = {}
            for field_name, aliases in FLOW_ALIASES.items():
                column = _match_column(list(row.keys()), aliases)
                value = clean_number(row.get(column)) if column else None
                values[field_name] = None if value is None or value < 0 else value
            try:
                candidate = FlowRow(symbol=symbol, trading_date=trading_date, **values)
            except (ValueError, TypeError):
                continue
            if candidate.is_empty:
                continue
            seen.add(trading_date)
            rows.append(candidate)
        rows.sort(key=lambda item: item.trading_date)
        return tuple(rows)


def _coerce_date(value: object) -> date | None:
    """Best-effort date parsing that refuses to guess."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return date.fromisoformat(str(isoformat())[:10])
        except ValueError:
            return None
    text = str(value).strip()
    if not text:
        return None
    for length, fmt in ((10, "%Y-%m-%d"), (10, "%d/%m/%Y"), (8, "%Y%m%d")):
        candidate = text[:length]
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None

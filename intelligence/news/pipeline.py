"""Bounded provider-to-repository news ingestion pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import requests

from intelligence.news.models import NewsItem
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import SentimentModel

logger = logging.getLogger(__name__)

CAFEF_COMPANY_CATALOG_URL = "https://cafefnew.mediacdn.vn/Search/company.json"
CAFEF_LISTED_EXCHANGES = frozenset({"hose", "hastc", "upcom"})
SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{1,32}")
COMPANY_PREFIXES = (
    "công ty cổ phần ", "ctcp ", "công ty tnhh ",
    "ngân hàng thương mại cổ phần ", "ngân hàng tmcp ",
    "tổng công ty ", "tập đoàn ",
)


EVENTS = (
    ("LEGAL", .95, ("khởi tố", "gian lận", "xử phạt", "đình chỉ", "thao túng")),
    ("EARNINGS", .85, ("lợi nhuận", "doanh thu", "bctc", "kết quả kinh doanh", "lỗ ròng")),
    ("MA", .80, ("m&a", "thâu tóm", "sáp nhập", "thoái vốn")),
    ("CAPITAL", .75, ("phát hành", "esop", "tăng vốn", "trái phiếu")),
    ("MACRO", .75, ("lãi suất", "lạm phát", "gdp", "tỷ giá", "ngân hàng nhà nước")),
    ("DIVIDEND", .70, ("cổ tức",)),
    ("CONTRACT", .65, ("trúng thầu", "ký hợp đồng", "hợp tác chiến lược")),
    ("MANAGEMENT", .60, ("bổ nhiệm", "từ nhiệm", "miễn nhiệm")),
)


def normalize_text(value: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def classify_event(title: str, body: str = "") -> tuple[str, float]:
    for event, importance, keywords in EVENTS:
        if any(word in title.lower() for word in keywords):
            return event, importance
    combined = f"{title} {body}".lower()
    for event, importance, keywords in EVENTS:
        if any(word in combined for word in keywords):
            return event, importance
    return "OTHER", .30


class TickerLinker:
    """Title-first linker that preserves per-ticker relevance."""

    def __init__(
        self,
        symbols: Iterable[str],
        aliases: Mapping[str, Iterable[str]] | None = None,
    ):
        normalized = tuple(dict.fromkeys(_normalize_symbol(value) for value in symbols))
        if not normalized:
            raise ValueError("ticker universe must not be empty")
        self.symbols = normalized
        alias_source = aliases or {}
        self.aliases = {
            symbol: tuple(dict.fromkeys(
                normalized_alias
                for value in alias_source.get(symbol, ())
                if (normalized_alias := normalize_text(value))
            ))
            for symbol in normalized
        }
        alternation = "|".join(
            re.escape(value)
            for value in sorted(normalized, key=lambda item: (-len(item), item))
        )
        self._symbol_pattern = re.compile(
            rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])"
        )

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)

    def link(self, item: NewsItem) -> NewsItem:
        title, body = item.title, f"{item.summary} {item.content}"
        title_symbols = _contextual_symbol_hits(title, self._symbol_pattern)
        body_symbols = _contextual_symbol_hits(body, self._symbol_pattern)
        scores: dict[str, float] = {}
        for ticker in self.symbols:
            aliases = self.aliases[ticker]
            title_hit = ticker in title_symbols or any(
                _contains_alias(title, alias) for alias in aliases
            )
            body_hit = ticker in body_symbols or any(
                _contains_alias(body, alias) for alias in aliases
            )
            if title_hit or body_hit:
                scores[ticker] = 1.0 if title_hit else .4
        ordered = tuple(sorted(scores, key=lambda key: (-scores[key], key)))
        return replace(item, tickers=ordered, primary_ticker=ordered[0] if ordered else None,
                       ticker_relevance=scores)


class CafeFCompanyCatalogProvider:
    """Load listed-company names from CafeF for alias enrichment only."""

    def __init__(
        self,
        url: str = CAFEF_COMPANY_CATALOG_URL,
        timeout: float = 15,
        request_get: Callable | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.request_get = request_get or requests.get

    def fetch(self) -> dict[str, tuple[str, ...]]:
        response = self.request_get(
            self.url,
            timeout=self.timeout,
            headers={"User-Agent": "VNStockBot/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CafeF company catalog must be a JSON list")
        result: dict[str, tuple[str, ...]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            redirect = str(row.get("RedirectUrl") or "")
            match = re.match(r"^/du-lieu/([^/]+)/", redirect, re.I)
            if match is None or match.group(1).lower() not in CAFEF_LISTED_EXCHANGES:
                continue
            try:
                symbol = _normalize_symbol(str(row.get("Symbol") or ""))
            except ValueError:
                continue
            aliases: list[str] = []
            for key in ("Title", "Description"):
                name = normalize_text(str(row.get(key) or ""))
                if not name:
                    continue
                aliases.append(name)
                simplified = _simplify_company_name(name)
                if simplified.casefold() != name.casefold():
                    aliases.append(simplified)
            result[symbol] = tuple(dict.fromkeys(aliases))
        if not result:
            raise ValueError("CafeF company catalog contains no listed equities")
        return result


def active_stock_symbols(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return the current stock universe already validated by the main database."""
    rows = connection.execute(
        "SELECT symbol FROM symbols WHERE is_active=1 "
        "AND instrument_type IN ('STOCK','COMMON_STOCK') ORDER BY symbol"
    ).fetchall()
    return tuple(_normalize_symbol(row[0]) for row in rows)


def build_ticker_linker(
    connection: sqlite3.Connection,
    catalog_provider: CafeFCompanyCatalogProvider,
) -> TickerLinker:
    """Build an all-symbol linker, retaining SQLite coverage if CafeF is down."""
    local_symbols = active_stock_symbols(connection)
    try:
        catalog = catalog_provider.fetch()
    except (OSError, ValueError, requests.RequestException):
        logger.exception("CafeF company catalog unavailable; using SQLite ticker universe")
        catalog = {}
    symbols = local_symbols or tuple(sorted(catalog))
    if not symbols:
        raise RuntimeError("no active stock symbols are available for news linking")
    aliases = {symbol: catalog.get(symbol, ()) for symbol in symbols}
    return TickerLinker(symbols, aliases)


def _normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(f"invalid ticker symbol: {value!r}")
    return symbol


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.I) is not None


def _contextual_symbol_hits(text: str, pattern: re.Pattern[str]) -> set[str]:
    """Accept explicit ticker mentions while rejecting ordinary uppercase words."""
    result: set[str] = set()
    for match in pattern.finditer(text):
        start, end = match.span()
        prefix = text[max(0, start - 32):start]
        suffix = text[end:end + 2]
        before = text[start - 1] if start else ""
        if (
            start == 0
            or re.search(r"(?:mã(?:\s+cổ\s+phiếu)?|cổ\s+phiếu|cp)\s*$", prefix, re.I)
            or before in "($#"
            or suffix.startswith(":")
            or (before == "(" and suffix.startswith(")"))
        ):
            result.add(match.group(0))
    return result


def _simplify_company_name(value: str) -> str:
    simplified = value.strip()
    changed = True
    while changed:
        changed = False
        folded = simplified.casefold()
        for prefix in COMPANY_PREFIXES:
            if folded.startswith(prefix.casefold()):
                simplified = simplified[len(prefix):].strip(" ,-–—")
                changed = True
                break
    return simplified if len(simplified) >= 3 else value.strip()


class CafeFRSSProvider:
    def __init__(self, url: str = "https://cafef.vn/thi-truong-chung-khoan.rss", timeout: float = 15):
        self.url, self.timeout = url, timeout

    def fetch(self, limit: int = 20) -> tuple[NewsItem, ...]:
        response = requests.get(self.url, timeout=self.timeout,
                                headers={"User-Agent": "VNStockBot/1.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content.replace(b"&nbsp;", b" "))
        items = []
        for node in root.findall(".//item")[:max(1, limit)]:
            title = normalize_text(node.findtext("title"))
            summary = normalize_text(node.findtext("description"))
            raw_url = normalize_text(node.findtext("link"))
            parts = urlsplit(raw_url)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            published = parsedate_to_datetime(node.findtext("pubDate"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            identifier = hashlib.sha256(url.encode()).hexdigest()
            event, importance = classify_event(title, summary)
            items.append(NewsItem(identifier, "cafef_rss", url, published.astimezone(timezone.utc),
                                  title, summary, event_type=event, event_importance=importance))
        return tuple(items)


class NewsIngestionService:
    def __init__(self, provider: CafeFRSSProvider, linker: TickerLinker,
                 sentiment: SentimentModel, repository: SQLiteNewsRepository):
        self.provider, self.linker, self.sentiment, self.repository = provider, linker, sentiment, repository

    def run_once(self, limit: int = 20) -> tuple[int, int]:
        inserted = duplicates = 0
        for raw in self.provider.fetch(limit):
            linked = self.linker.link(raw)
            analyzed = replace(linked, sentiment=self.sentiment.analyze(linked))
            if self.repository.save(analyzed): inserted += 1
            else: duplicates += 1
        return inserted, duplicates

"""Bounded provider-to-repository news ingestion pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit
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
    ("EARNINGS", .85, (
        "lợi nhuận", "doanh thu", "bctc", "kết quả kinh doanh", "lỗ ròng",
        "lãi ròng", "lnst", "lợi nhuận sau thuế", "lãi sau thuế",
        "kết quả quý", "kết quả tháng", "doanh thu quý", "lợi nhuận quý",
    )),
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


CAFEF_RSS_URLS = (
    "https://cafef.vn/thi-truong-chung-khoan.rss",
    "https://cafef.vn/doanh-nghiep.rss",
    "https://cafef.vn/tai-chinh-ngan-hang.rss",
    "https://cafef.vn/smart-money.rss",
)


class CafeFRSSProvider:
    """Merge CafeF's official finance RSS channels into one fresh stream."""

    def __init__(
        self,
        url: str | None = None,
        timeout: float = 15,
        *,
        urls: Iterable[str] | None = None,
        request_get: Callable | None = None,
    ):
        self.urls = tuple(urls or ((url,) if url else CAFEF_RSS_URLS))
        if not self.urls:
            raise ValueError("at least one CafeF RSS URL is required")
        self.url, self.timeout = self.urls[0], timeout
        self.request_get = request_get or requests.get

    def fetch(self, limit: int = 20) -> tuple[NewsItem, ...]:
        wanted = max(1, limit)
        items: dict[str, NewsItem] = {}
        errors: list[Exception] = []
        for feed_url in self.urls:
            try:
                response = self.request_get(
                    feed_url, timeout=self.timeout,
                    headers={"User-Agent": "VNStockBot/1.0"},
                )
                response.raise_for_status()
                root = ET.fromstring(response.content.replace(b"&nbsp;", b" "))
            except (OSError, ValueError, ET.ParseError, requests.RequestException) as error:
                logger.warning("CafeF RSS fetch failed url=%s", feed_url)
                errors.append(error)
                continue
            for node in root.findall(".//item")[:wanted]:
                title = normalize_text(node.findtext("title"))
                summary = normalize_text(node.findtext("description"))
                raw_url = normalize_text(node.findtext("link"))
                parts = urlsplit(raw_url)
                clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
                if not title or not clean_url:
                    continue
                published = parsedate_to_datetime(node.findtext("pubDate"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                identifier = hashlib.sha256(clean_url.encode()).hexdigest()
                event, importance = classify_event(title, summary)
                items[clean_url] = NewsItem(
                    identifier, "cafef_rss", clean_url,
                    published.astimezone(timezone.utc), title, summary,
                    event_type=event, event_importance=importance,
                )
        if not items and errors:
            raise ConnectionError("all configured CafeF RSS feeds failed") from errors[0]
        return tuple(sorted(items.values(), key=lambda item: item.published_at, reverse=True)[:wanted])


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


CAFEF_TICKER_NEWS_URL = "https://cafef.vn/{symbol}/trang-1.html"
VIETNAM_TZ = timezone(timedelta(hours=7))


class CafeFTickerNewsProvider:
    """Fetch the current ticker-tag page instead of the stale event calendar."""

    def __init__(
        self,
        base_url: str = CAFEF_TICKER_NEWS_URL,
        timeout: float = 15,
        request_get: Callable | None = None,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.request_get = request_get or requests.get

    def fetch(
        self,
        symbol: str,
        limit: int = 5,
        max_age_days: int = 30,
        *,
        now: datetime | None = None,
    ) -> tuple[NewsItem, ...]:
        normalized_symbol = _normalize_symbol(symbol)
        url = self.base_url.format(symbol=normalized_symbol.lower())
        response = self.request_get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VNStockBot/1.0"},
        )
        response.raise_for_status()
        content = response.text

        return self.parse_html(
            content, normalized_symbol, limit=limit, max_age_days=max_age_days, now=now
        )

    def parse_html(
        self,
        html_content: str,
        symbol: str,
        limit: int = 5,
        max_age_days: int = 30,
        *,
        now: datetime | None = None,
    ) -> tuple[NewsItem, ...]:
        current_time = now or datetime.now(timezone.utc)
        min_date = current_time - timedelta(days=max_age_days)

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")
        tag_nodes = soup.select("div.tlitem")
        if tag_nodes:
            return self._parse_tag_nodes(
                tag_nodes, symbol, limit=limit, min_date=min_date,
                current_time=current_time,
            )

        div_events = soup.find(id="divEvents")
        if not div_events:
            return ()

        items: list[NewsItem] = []
        seen_urls: set[str] = set()

        for node in div_events.find_all(["li", "div", "p", "tr"]):
            text = node.get_text(" ", strip=True)
            match_date = re.search(r"(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{1,2})?)", text)
            anchor = node.find("a", href=True)
            if not match_date or not anchor:
                continue

            date_str = match_date.group(1)
            try:
                if " " in date_str:
                    dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M").replace(tzinfo=VIETNAM_TZ)
                else:
                    dt = datetime.strptime(date_str, "%d/%m/%Y").replace(tzinfo=VIETNAM_TZ)
                pub_utc = dt.astimezone(timezone.utc)
            except Exception:
                continue

            if pub_utc < min_date or pub_utc > current_time + timedelta(days=1):
                continue

            raw_href = anchor["href"].strip()
            if raw_href.startswith("//"):
                raw_url = "https:" + raw_href
            elif raw_href.startswith("/"):
                raw_url = "https://s.cafef.vn" + raw_href
            else:
                raw_url = raw_href

            parts = urlsplit(raw_url)
            clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            title = normalize_text(anchor.get_text(strip=True))
            if not title or len(title) < 5:
                continue

            identifier = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()
            event, importance = classify_event(title, "")

            items.append(
                NewsItem(
                    id=identifier,
                    source="cafef_ticker",
                    url=clean_url,
                    published_at=pub_utc,
                    title=title,
                    summary="",
                    content="",
                    tickers=(symbol,),
                    primary_ticker=symbol,
                    ticker_relevance={symbol: 1.0},
                    event_type=event,
                    event_importance=importance,
                )
            )

        items.sort(key=lambda x: x.published_at, reverse=True)
        return tuple(items[:max(1, limit)])

    @staticmethod
    def _parse_tag_nodes(
        nodes, symbol: str, *, limit: int, min_date: datetime,
        current_time: datetime,
    ) -> tuple[NewsItem, ...]:
        items: list[NewsItem] = []
        seen_urls: set[str] = set()
        for node in nodes:
            anchor = node.select_one("a.box-category-link-title")
            time_node = node.select_one("span.time")
            if anchor is None or time_node is None or not anchor.get("href"):
                continue
            try:
                local_time = datetime.strptime(
                    normalize_text(time_node.get_text(" ", strip=True)),
                    "%d/%m/%Y %H:%M",
                ).replace(tzinfo=VIETNAM_TZ)
            except ValueError:
                continue
            published = local_time.astimezone(timezone.utc)
            if published < min_date or published > current_time + timedelta(days=1):
                continue
            raw_url = urljoin("https://cafef.vn/", anchor["href"].strip())
            parts = urlsplit(raw_url)
            clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if clean_url in seen_urls:
                continue
            title = normalize_text(anchor.get_text(" ", strip=True))
            summary_node = node.select_one("p.sapo")
            summary = normalize_text(
                summary_node.get_text(" ", strip=True) if summary_node else ""
            )
            if not title:
                continue
            seen_urls.add(clean_url)
            event, importance = classify_event(title, summary)
            direct = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])",
                f"{title} {summary}", re.I,
            ) is not None
            items.append(NewsItem(
                id=hashlib.sha256(clean_url.encode("utf-8")).hexdigest(),
                source="cafef_ticker_tag", url=clean_url,
                published_at=published, title=title, summary=summary,
                tickers=(symbol,), primary_ticker=symbol if direct else None,
                ticker_relevance={symbol: 1.0 if direct else .4}, event_type=event,
                event_importance=importance,
            ))
        items.sort(key=lambda item: item.published_at, reverse=True)
        return tuple(items[:max(1, limit)])


def refresh_ticker_news(
    symbol: str,
    *,
    repository: SQLiteNewsRepository,
    sentiment_model: SentimentModel,
    provider: CafeFTickerNewsProvider | None = None,
    limit: int = 5,
    max_age_days: int = 30,
    now: datetime | None = None,
) -> int:
    """Fetch, analyze and persist ticker-specific news for a single symbol."""
    prov = provider or CafeFTickerNewsProvider()
    items = prov.fetch(symbol, limit=limit, max_age_days=max_age_days, now=now)
    inserted = 0
    for raw in items:
        analyzed = replace(raw, sentiment=sentiment_model.analyze(raw))
        if repository.save(analyzed):
            inserted += 1
    return len(items)


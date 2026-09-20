"""Bounded provider-to-repository news ingestion pipeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import requests

from intelligence.news.models import NewsItem
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import SentimentModel


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

    def __init__(self, aliases: dict[str, tuple[str, ...]] | None = None):
        self.aliases = aliases or {
            "ACB": ("ACB", "ngân hàng á châu"), "FPT": ("FPT",),
            "HPG": ("HPG", "hòa phát"), "VCB": ("VCB", "vietcombank"),
            "VHM": ("VHM", "vinhomes"), "MWG": ("MWG", "thế giới di động"),
            "SSI": ("SSI",), "VND": ("VNDIRECT", "$VND", "#VND"),
        }

    def link(self, item: NewsItem) -> NewsItem:
        title, body = item.title, f"{item.summary} {item.content}"
        scores = {}
        for ticker, aliases in self.aliases.items():
            title_hit = any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", title, re.I) for alias in aliases)
            body_hit = any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", body, re.I) for alias in aliases)
            if title_hit or body_hit:
                scores[ticker] = 1.0 if title_hit else .4
        ordered = tuple(sorted(scores, key=lambda key: (-scores[key], key)))
        return replace(item, tickers=ordered, primary_ticker=ordered[0] if ordered else None,
                       ticker_relevance=scores)


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

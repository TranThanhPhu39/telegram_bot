"""Backward-compatible SQLite repository for normalized news sentiment."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult


NEWS_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS news_items (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
 published_at TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
 content TEXT NOT NULL DEFAULT '', event_type TEXT NOT NULL DEFAULT 'OTHER',
 event_importance REAL NOT NULL DEFAULT 0.3,
 sentiment_label TEXT, sentiment_score REAL,
 probability_positive REAL, probability_neutral REAL, probability_negative REAL,
 model_confidence REAL, model_backend TEXT, model_name TEXT, model_version TEXT,
 analyzed_at TEXT, calibration_version TEXT
)
"""

NEWS_TICKERS_SQL = """
CREATE TABLE IF NOT EXISTS news_tickers (
 news_id TEXT NOT NULL, ticker TEXT NOT NULL, is_primary INTEGER NOT NULL DEFAULT 0,
 relevance REAL NOT NULL DEFAULT 0.0,
 PRIMARY KEY(news_id,ticker), FOREIGN KEY(news_id) REFERENCES news_items(id) ON DELETE CASCADE,
 CHECK(is_primary IN (0,1)), CHECK(relevance>=0 AND relevance<=1)
)
"""

_ADDITIVE_COLUMNS = {
    "event_importance": "REAL NOT NULL DEFAULT 0.3",
    "probability_positive": "REAL",
    "probability_neutral": "REAL",
    "probability_negative": "REAL",
    "model_confidence": "REAL",
    "model_backend": "TEXT",
    "model_name": "TEXT",
    "analyzed_at": "TEXT",
    "calibration_version": "TEXT",
}


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class SQLiteNewsRepository:
    def __init__(self, path: str | Path = "news_sentiment.db") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def migrate(self) -> None:
        with self.connection:
            self.connection.execute(NEWS_ITEMS_SQL)
            existing = {row["name"] for row in self.connection.execute("PRAGMA table_info(news_items)")}
            for name, definition in _ADDITIVE_COLUMNS.items():
                if name not in existing:
                    self.connection.execute(f"ALTER TABLE news_items ADD COLUMN {name} {definition}")
            self.connection.execute(NEWS_TICKERS_SQL)
            ticker_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(news_tickers)")}
            if "relevance" not in ticker_columns:
                self.connection.execute("ALTER TABLE news_tickers ADD COLUMN relevance REAL NOT NULL DEFAULT 0.0")

    def save(self, item: NewsItem) -> bool:
        sentiment = item.sentiment
        values = (
            item.id, item.source, item.url, _utc(item.published_at), item.title,
            item.summary, item.content, item.event_type, item.event_importance,
            sentiment.label.value if sentiment else None,
            sentiment.score if sentiment else None,
            sentiment.probability_positive if sentiment else None,
            sentiment.probability_neutral if sentiment else None,
            sentiment.probability_negative if sentiment else None,
            sentiment.model_confidence if sentiment else None,
            sentiment.backend if sentiment else None,
            sentiment.model_name if sentiment else None,
            sentiment.model_version if sentiment else None,
            _utc(sentiment.analyzed_at) if sentiment else None,
            sentiment.calibration_version if sentiment else None,
        )
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO news_items (id,source,url,published_at,title,summary,content," 
                "event_type,event_importance,sentiment_label,sentiment_score,probability_positive," 
                "probability_neutral,probability_negative,model_confidence,model_backend,model_name," 
                "model_version,analyzed_at,calibration_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
            if cursor.rowcount == 0:
                existing = self.connection.execute(
                    "SELECT id FROM news_items WHERE id=? OR url=? LIMIT 1",
                    (item.id, item.url),
                ).fetchone()
                if existing is not None:
                    self._replace_ticker_links(existing["id"], item)
                return False
            self._replace_ticker_links(item.id, item)
        return True

    def _replace_ticker_links(self, news_id: str, item: NewsItem) -> None:
        self.connection.execute("DELETE FROM news_tickers WHERE news_id=?", (news_id,))
        self.connection.executemany(
            "INSERT INTO news_tickers(news_id,ticker,is_primary,relevance) VALUES(?,?,?,?)",
            [(news_id, ticker, int(ticker == item.primary_ticker),
              item.ticker_relevance.get(ticker, 0.0)) for ticker in item.tickers],
        )

    def get(self, item_id: str) -> NewsItem | None:
        row = self.connection.execute("SELECT * FROM news_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return None
        ticker_rows = self.connection.execute(
            "SELECT * FROM news_tickers WHERE news_id=? ORDER BY is_primary DESC,ticker", (item_id,)
        ).fetchall()
        sentiment = None
        if row["sentiment_label"] is not None and row["probability_positive"] is not None:
            sentiment = SentimentResult(
                SentimentLabel(row["sentiment_label"]), row["probability_positive"],
                row["probability_neutral"], row["probability_negative"],
                row["model_confidence"], row["model_backend"], row["model_name"],
                row["model_version"], datetime.fromisoformat(row["analyzed_at"]),
                row["calibration_version"],
            )
        return NewsItem(
            row["id"], row["source"], row["url"], datetime.fromisoformat(row["published_at"]),
            row["title"], row["summary"] or "", row["content"] or "",
            tuple(item["ticker"] for item in ticker_rows),
            next((item["ticker"] for item in ticker_rows if item["is_primary"]), None),
            {item["ticker"]: item["relevance"] for item in ticker_rows},
            row["event_type"], row["event_importance"], sentiment,
        )

    def ticker_article_counts(self, since: datetime) -> dict[str, int]:
        """Read-only: distinct articles per linked ticker published since ``since``.

        Used by the Phase 25 coverage worker to tell "no relevant news in the
        window" (MISSING) from "news exists" (READY). It never infers sentiment.
        """
        rows = self.connection.execute(
            "SELECT t.ticker AS ticker, COUNT(DISTINCT n.id) AS articles "
            "FROM news_tickers t JOIN news_items n ON n.id=t.news_id "
            "WHERE n.published_at >= ? GROUP BY t.ticker",
            (_utc(since),),
        ).fetchall()
        return {row["ticker"]: int(row["articles"]) for row in rows}

    def latest_for_ticker(self, ticker: str, limit: int = 5) -> tuple[NewsItem, ...]:
        rows = self.connection.execute(
            "SELECT n.id FROM news_items n JOIN news_tickers t ON t.news_id=n.id "
            "WHERE t.ticker=? ORDER BY n.published_at DESC LIMIT ?",
            (ticker.strip().upper(), max(1, limit)),
        ).fetchall()
        return tuple(item for row in rows if (item := self.get(row["id"])) is not None)

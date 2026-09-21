from datetime import datetime, timezone
import sqlite3

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.repository import SQLiteNewsRepository


def sample():
    now = datetime.now(timezone.utc)
    sentiment = SentimentResult(SentimentLabel.NEGATIVE, .05, .05, .9, .9,
        "phobert", "FiinGroup/phobert-finetuned", "hf", now)
    return NewsItem("n1", "cafef", "https://example.test/n1", now, "ACB bị xử phạt",
        tickers=("ACB", "VCB"), primary_ticker="ACB",
        ticker_relevance={"ACB": 1.0, "VCB": .2}, event_type="LEGAL",
        event_importance=.95, sentiment=sentiment)


def test_repository_round_trip_probabilities_and_relevance(tmp_path):
    repo = SQLiteNewsRepository(tmp_path / "news.db")
    assert repo.save(sample()) is True
    assert repo.save(sample()) is False
    loaded = repo.get("n1")
    assert loaded.sentiment.probability_negative == .9
    assert loaded.sentiment.backend == "phobert"
    assert loaded.primary_ticker == "ACB"
    assert loaded.ticker_relevance == {"ACB": 1.0, "VCB": .2}
    assert repo.latest_for_ticker("acb") == (loaded,)


def test_migration_adds_columns_without_dropping_legacy_row(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE news_items(id TEXT PRIMARY KEY,source TEXT,url TEXT,published_at TEXT,title TEXT,summary TEXT,content TEXT,event_type TEXT,sentiment_label TEXT,sentiment_score REAL,confidence REAL,importance REAL,reason_codes TEXT,model_version TEXT)")
    connection.execute("INSERT INTO news_items VALUES('old','cafef','u','2026-01-01T00:00:00+00:00','t','','','OTHER','neutral',0,0.5,0.3,'[]','v1')")
    connection.commit(); connection.close()
    repo = SQLiteNewsRepository(path)
    columns = {row["name"] for row in repo.connection.execute("PRAGMA table_info(news_items)")}
    assert "probability_positive" in columns and "model_backend" in columns
    assert repo.connection.execute("SELECT COUNT(*) FROM news_items WHERE id='old'").fetchone()[0] == 1


def test_duplicate_news_refreshes_ticker_links_without_reinserting(tmp_path):
    repo = SQLiteNewsRepository(tmp_path / "news.db")
    original = NewsItem(
        "dynamic", "cafef_rss", "https://example.test/dynamic",
        datetime.now(timezone.utc), "DGC công bố kết quả",
    )
    assert repo.save(original) is True
    relinked = NewsItem(
        original.id, original.source, original.url, original.published_at,
        original.title, tickers=("DGC",), primary_ticker="DGC",
        ticker_relevance={"DGC": 1.0},
    )
    assert repo.save(relinked) is False
    loaded = repo.latest_for_ticker("DGC")
    assert len(loaded) == 1
    assert loaded[0].primary_ticker == "DGC"

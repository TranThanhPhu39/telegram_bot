from datetime import datetime, timedelta, timezone

from intelligence.news.benchmark import run_benchmark
from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.pipeline import NewsIngestionService, TickerLinker, classify_event
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import LexiconSentimentModel
from intelligence.news.service import SentimentQueryService


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def item(identifier="1", *, title="ACB lợi nhuận tăng", published=NOW,
         event="EARNINGS", negative=.05, confidence=.9, primary="ACB"):
    sentiment = SentimentResult(
        SentimentLabel.NEGATIVE if negative > .5 else SentimentLabel.POSITIVE,
        .9-negative, .1, negative, confidence, "test", "test", "1", NOW,
    )
    return NewsItem(identifier, "test", f"https://x/{identifier}", published, title,
                    tickers=(primary,), primary_ticker=primary,
                    ticker_relevance={primary: 1.0}, event_type=event,
                    event_importance=.9, sentiment=sentiment)


def test_linker_event_dedup_aggregate_and_benchmark(tmp_path):
    linked = TickerLinker().link(NewsItem("raw", "x", "https://x/raw", NOW,
                                             "ACB bị khởi tố"))
    assert linked.primary_ticker == "ACB"
    assert linked.ticker_relevance["ACB"] == 1.0
    assert classify_event(linked.title)[0] == "LEGAL"
    repository = SQLiteNewsRepository(tmp_path / "news.db")
    analyzed = item()
    assert repository.save(analyzed)
    assert not repository.save(analyzed)
    aggregate = SentimentQueryService(repository).ticker_sentiment("ACB", now=NOW)
    assert aggregate and aggregate.article_count == 1 and aggregate.score > 0
    result = run_benchmark(LexiconSentimentModel(now=lambda: NOW),
                           "tests/fixtures/sentiment_benchmark.csv")
    assert result.total == 10
    assert result.accuracy >= .8


def test_severe_negative_is_fail_closed_by_primary_confidence_and_age(tmp_path):
    repository = SQLiteNewsRepository(tmp_path / "news.db")
    service = SentimentQueryService(repository)
    repository.save(item("ok", event="LEGAL", negative=.8, confidence=.9))
    assert service.severe_negative("ACB", now=NOW) is not None
    repository.save(item("low", event="LEGAL", negative=.8, confidence=.5))
    repository.save(item("old", event="LEGAL", negative=.8, confidence=.9,
                         published=NOW-timedelta(hours=49)))
    assert service.severe_negative("FPT", now=NOW) is None


def test_ingestion_is_bounded_and_idempotent(tmp_path):
    raw = NewsItem("raw", "x", "https://x/raw", NOW, "ACB lợi nhuận tăng")
    class Provider:
        def fetch(self, limit):
            assert limit == 1
            return (raw,)
    service = NewsIngestionService(Provider(), TickerLinker(),
                                   LexiconSentimentModel(now=lambda: NOW),
                                   SQLiteNewsRepository(tmp_path / "news.db"))
    assert service.run_once(1) == (1, 0)
    assert service.run_once(1) == (0, 1)

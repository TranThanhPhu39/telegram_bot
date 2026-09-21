from datetime import datetime, timedelta, timezone
import sqlite3

from intelligence.news.benchmark import run_benchmark
from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.pipeline import (
    CafeFCompanyCatalogProvider,
    NewsIngestionService,
    TickerLinker,
    active_stock_symbols,
    build_ticker_linker,
    classify_event,
)
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
    linked = TickerLinker(("ACB",)).link(NewsItem("raw", "x", "https://x/raw", NOW,
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
    service = NewsIngestionService(Provider(), TickerLinker(("ACB",)),
                                   LexiconSentimentModel(now=lambda: NOW),
                                   SQLiteNewsRepository(tmp_path / "news.db"))
    assert service.run_once(1) == (1, 0)
    assert service.run_once(1) == (0, 1)


def test_dynamic_linker_supports_arbitrary_tickers_and_company_names():
    linker = TickerLinker(
        ("DGC", "KDH", "VIX"),
        {"DGC": ("Hóa chất Đức Giang",), "KDH": ("Nhà Khang Điền",)},
    )
    by_symbol = linker.link(NewsItem(
        "dgc", "x", "https://x/dgc", NOW,
        "DGC công bố kết quả kinh doanh", "Cổ phiếu KDH cũng được nhắc tới",
    ))
    assert by_symbol.tickers == ("DGC", "KDH")
    assert by_symbol.primary_ticker == "DGC"
    assert by_symbol.ticker_relevance == {"DGC": 1.0, "KDH": .4}

    by_name = linker.link(NewsItem(
        "name", "x", "https://x/name", NOW,
        "Hóa chất Đức Giang tăng trưởng mạnh",
    ))
    assert by_name.tickers == ("DGC",)
    assert linker.link(NewsItem(
        "lower", "x", "https://x/lower", NOW,
        "Doanh nghiệp đang xây dựng chiến lược vix mới",
    )).tickers == ()


def test_dynamic_linker_rejects_ambiguous_words_without_ticker_context():
    linker = TickerLinker(("CEO", "USD"))
    ambiguous = linker.link(NewsItem(
        "ambiguous", "x", "https://x/ambiguous", NOW,
        "Chủ tịch, CEO nói về dự án trị giá 2 tỷ USD",
    ))
    assert ambiguous.tickers == ()
    explicit = linker.link(NewsItem(
        "explicit", "x", "https://x/explicit", NOW,
        "Cổ phiếu CEO tăng giá", "Mã USD cũng được theo dõi",
    ))
    assert explicit.tickers == ("CEO", "USD")


def test_catalog_and_sqlite_universe_build_all_symbol_linker():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"Symbol": "DGC", "Title": "CTCP Tập đoàn Hóa chất Đức Giang",
                 "Description": "CTCP Tập đoàn Hóa chất Đức Giang",
                 "RedirectUrl": "/du-lieu/hose/dgc.chn"},
                {"Symbol": "KDH", "Title": "CTCP Đầu tư và Kinh doanh Nhà Khang Điền",
                 "Description": "CTCP Đầu tư và Kinh doanh Nhà Khang Điền",
                 "RedirectUrl": "/du-lieu/hose/kdh.chn"},
                {"Symbol": "FPT", "Title": "Công ty Cổ phần FPT",
                 "Description": "Công ty Cổ phần FPT",
                 "RedirectUrl": "/du-lieu/hose/fpt.chn"},
                {"Symbol": "OTC", "Title": "OTC test", "Description": "OTC test",
                 "RedirectUrl": "/du-lieu/otc/otc.chn"},
            ]

    provider = CafeFCompanyCatalogProvider(request_get=lambda *args, **kwargs: Response())
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE symbols(symbol TEXT PRIMARY KEY,instrument_type TEXT,is_active INTEGER)"
    )
    connection.executemany(
        "INSERT INTO symbols VALUES(?,?,?)",
        (("DGC", "STOCK", 1), ("KDH", "COMMON_STOCK", 1),
         ("FPT", "STOCK", 1), ("OLD", "STOCK", 0)),
    )
    assert active_stock_symbols(connection) == ("DGC", "FPT", "KDH")
    linker = build_ticker_linker(connection, provider)
    assert linker.symbol_count == 3
    linked = linker.link(NewsItem(
        "catalog", "x", "https://x/catalog", NOW,
        "Tập đoàn Hóa chất Đức Giang báo lãi",
    ))
    assert linked.tickers == ("DGC",)
    assert linker.link(NewsItem(
        "short-name", "x", "https://x/short-name", NOW,
        "Lịch cổ tức tuần này: VPBank, FPT lăn chốt",
    )).tickers == ("FPT",)


def test_catalog_failure_falls_back_to_all_sqlite_symbols():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE symbols(symbol TEXT PRIMARY KEY,instrument_type TEXT,is_active INTEGER)"
    )
    connection.executemany(
        "INSERT INTO symbols VALUES(?,?,?)",
        (("DGC", "STOCK", 1), ("KDH", "STOCK", 1)),
    )
    provider = CafeFCompanyCatalogProvider(
        request_get=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline"))
    )
    linker = build_ticker_linker(connection, provider)
    assert linker.symbol_count == 2
    assert linker.link(NewsItem(
        "fallback", "x", "https://x/fallback", NOW, "KDH tăng giá",
    )).tickers == ("KDH",)

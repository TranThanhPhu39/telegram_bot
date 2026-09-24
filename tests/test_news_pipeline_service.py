from datetime import datetime, timedelta, timezone
import sqlite3
import pytest

from intelligence.news.benchmark import benchmark_decay_profiles, run_benchmark
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
from intelligence.news import sentiment as sentiment_module
from intelligence.news.sentiment import (
    FinancialHeadlineCalibrationModel, LexiconSentimentModel,
)
from intelligence.news.service import SentimentQueryService
from runtime.views import NewsItemView
from telegram_bot.formatters import format_news


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
    financial_result = run_benchmark(
        FinancialHeadlineCalibrationModel(LexiconSentimentModel(now=lambda: NOW)),
        "tests/fixtures/financial_sentiment_benchmark.csv",
    )
    assert financial_result.total == 18
    assert financial_result.accuracy >= .95

    decay = benchmark_decay_profiles()
    equal = next(profile for profile in decay if profile.name == "equal")
    current = next(profile for profile in decay if profile.name == "half-life-24h")
    assert equal.normalized_weights == (.2, .2, .2, .2, .2)
    assert current.newest_share > .60
    assert current.normalized_weights[3] < .01  # seven-day article
    assert current.oldest_share < 1e-6  # thirty-day article


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


# --- Issue 5: shared sentiment model singleton across news runners --------


def test_get_shared_sentiment_model_is_a_process_wide_singleton(monkeypatch):
    """The periodic NewsRefreshRunner and the new on-demand
    TargetedNewsRefreshWorker (runtime/news_refresh.py) each build their own
    runner, but both must reuse one sentiment model instance -- PhoBERT is
    meant to load at most once per process."""
    monkeypatch.setattr(sentiment_module, "_shared_model", None)
    monkeypatch.setenv("SENTIMENT_MODEL_BACKEND", "lexicon")  # cheap, no network

    first = sentiment_module.get_shared_sentiment_model()
    second = sentiment_module.get_shared_sentiment_model()

    assert first is second
    assert isinstance(first, FinancialHeadlineCalibrationModel)
    assert isinstance(first.model, LexiconSentimentModel)
    headline = NewsItem(
        "calibration", "test", "https://example.test/calibration", NOW,
        "FPT lãi ròng gần 30 tỷ đồng mỗi ngày trong tháng 8",
    )
    assert first.analyze(headline).label.value == "positive"


def test_latest_five_sentiment_and_canonical_selection(tmp_path):
    repository = SQLiteNewsRepository(tmp_path / "news_canonical.db")
    service = SentimentQueryService(repository)

    # 1. Zero eligible articles returns None (MISSING, not Neutral)
    assert service.ticker_sentiment("FPT", now=NOW) is None
    assert service.eligible_articles("FPT", now=NOW) == ()
    assert service.latest_news("FPT", now=NOW) == ()

    # 2. Add 7 articles with different ages for FPT:
    # 3 days ago (positive), 5 days ago (positive), 10 days ago (negative),
    # 20 days ago (positive), 25 days ago (positive), 28 days ago (negative),
    # 32 days ago (should be excluded by max_age_days=30)
    ages_days = [3, 5, 10, 20, 25, 28, 32]
    for idx, d in enumerate(ages_days):
        published = NOW - timedelta(days=d)
        is_neg = (idx % 2 == 1)
        repository.save(item(
            f"fpt-{idx}",
            title=f"FPT tin số {idx}",
            published=published,
            negative=0.8 if is_neg else 0.1,
            confidence=0.9,
            primary="FPT",
        ))

    # 3. eligible_articles should return exactly the newest 5 (ages 3, 5, 10, 20, 25)
    eligible = service.eligible_articles("FPT", limit=5, max_age_days=30, now=NOW)
    assert len(eligible) == 5
    assert eligible[0].id == "fpt-0"  # 3 days ago
    assert eligible[1].id == "fpt-1"  # 5 days ago
    assert eligible[2].id == "fpt-2"  # 10 days ago
    assert eligible[3].id == "fpt-3"  # 20 days ago
    assert eligible[4].id == "fpt-4"  # 25 days ago

    # 4. latest_news shares the exact same selection path
    news = service.latest_news("FPT", limit=5, max_age_days=30, now=NOW)
    assert [x.id for x in news] == [x.id for x in eligible]

    # 5. ticker_sentiment computes on these 5 articles
    agg = service.ticker_sentiment("FPT", now=NOW)
    assert agg is not None
    assert agg.article_count == 5
    assert agg.hours == 30 * 24

    # 6. severe_negative still checks 48 hours independently
    # None of the FPT articles above are <= 48h
    assert service.severe_negative("FPT", now=NOW) is None
    # Add a severe negative article at 24h
    repository.save(item("fpt-urgent", event="LEGAL", negative=0.9, confidence=0.95,
                         published=NOW - timedelta(hours=24), primary="FPT"))
    assert service.severe_negative("FPT", now=NOW) is not None


# -------------------------------------------------- Issue 5: Targeted ticker news refresh
def test_cafef_ticker_news_provider_parses_html():
    from intelligence.news.pipeline import CafeFTickerNewsProvider

    html_sample = """
    <html><body>
    <div id="divEvents">
        <ul>
            <li>
                <span>15/09/2026 08:30</span>
                <a href="/du-lieu/HC1-2976744/hc1-tra-co-tuc.chn?utm_source=du-lieu">
                    HC1: 22.09.2026, ngày GDKHQ trả cổ tức bằng tiền mặt
                </a>
            </li>
            <li>
                <span>10/09/2026</span>
                <a href="//cafef.vn/hc1-dai-hoi-co-dong.chn">
                    HC1: Nghị quyết Đại hội đồng cổ đông bất thường
                </a>
            </li>
            <li>
                <span>01/08/2026</span>
                <a href="/du-lieu/HC1-old.chn">
                    HC1: Tin cũ hơn 30 ngày bị loại
                </a>
            </li>
        </ul>
    </div>
    </body></html>
    """
    provider = CafeFTickerNewsProvider()
    items = provider.parse_html(html_sample, "HC1", limit=5, max_age_days=30, now=NOW)
    assert len(items) == 2
    assert items[0].primary_ticker == "HC1"
    assert items[0].tickers == ("HC1",)
    assert items[0].source == "cafef_ticker"
    assert "HC1: 22.09.2026" in items[0].title
    assert items[0].url == "https://s.cafef.vn/du-lieu/HC1-2976744/hc1-tra-co-tuc.chn"
    assert items[1].url == "https://cafef.vn/hc1-dai-hoi-co-dong.chn"
    assert items[0].published_at.year == 2026
    assert items[0].published_at.month == 9
    assert items[0].published_at.day == 15
    assert items[0].retrieved_at == NOW


def test_cafef_ticker_fetch_bypasses_http_cache_and_stamps_retrieval_time():
    from intelligence.news.pipeline import CafeFTickerNewsProvider

    calls = []

    class Response:
        text = '<div id="divEvents"><p>19/09/2026 <a href="/fpt.chn">FPT tăng trưởng</a></p></div>'

        def raise_for_status(self):
            return None

    def request_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    items = CafeFTickerNewsProvider(request_get=request_get).fetch("FPT", now=NOW)

    assert len(items) == 1
    assert items[0].retrieved_at == NOW
    assert calls[0][1]["headers"]["Cache-Control"] == "no-cache"
    assert calls[0][1]["headers"]["Pragma"] == "no-cache"


def test_news_formatter_exposes_retrieval_time_and_fallback_quality():
    result = format_news("FPT", (NewsItemView(
        published_at=NOW,
        title="FPT lập kỷ lục, ký hợp đồng mới",
        source="cafef_ticker",
        event_type="CONTRACT",
        sentiment_label="neutral",
        url="https://cafef.vn/fpt.chn",
        retrieved_at=NOW,
        sentiment_backend="lexicon_fallback",
    ),))
    assert "Tải lúc:" in result
    assert "fallback từ khóa" in result


def test_cafef_ticker_provider_distinguishes_transport_and_page_shape_errors():
    from intelligence.news.pipeline import CafeFTickerNewsProvider, NewsProviderFetchError

    class FailedResponse:
        text = "<html><body>blocked</body></html>"

        def raise_for_status(self):
            raise RuntimeError("HTTP 403")

    provider = CafeFTickerNewsProvider(request_get=lambda *a, **kw: FailedResponse())
    with pytest.raises(NewsProviderFetchError, match="request failed"):
        provider.fetch("VIC", now=NOW)
    with pytest.raises(NewsProviderFetchError, match="#divEvents"):
        provider.parse_html("<html><body></body></html>", "VIC", now=NOW)


def test_refresh_ticker_news_populates_repository_and_sentiment(tmp_path):
    from intelligence.news.pipeline import CafeFTickerNewsProvider, refresh_ticker_news

    html_sample = """
    <div id="divEvents">
        <p>18/09/2026 09:00 <a href="/du-lieu/HC1-1.chn">HC1: Doanh thu quý 3 tăng trưởng mạnh</a></p>
        <p>12/09/2026 <a href="/du-lieu/HC1-2.chn">HC1: Ký hợp đồng xây dựng dự án mới</a></p>
    </div>
    """
    class FakeResponse:
        text = html_sample
        def raise_for_status(self): pass

    provider = CafeFTickerNewsProvider(request_get=lambda *a, **kw: FakeResponse())
    repo = SQLiteNewsRepository(tmp_path / "news.db")
    model = LexiconSentimentModel(now=lambda: NOW)

    count = refresh_ticker_news("HC1", repository=repo, sentiment_model=model, provider=provider, now=NOW)
    assert count == 2

    # Querying through SentimentQueryService immediately sees HC1 articles
    service = SentimentQueryService(repo)
    news = service.latest_news("HC1", now=NOW)
    assert len(news) == 2
    assert news[0].primary_ticker == "HC1"
    assert news[0].sentiment is not None

    agg = service.ticker_sentiment("HC1", now=NOW)
    assert agg is not None
    assert agg.article_count == 2
    assert agg.ticker == "HC1"


def test_ticker_refetch_rescores_cached_recent_articles_without_faking_fetch_time(tmp_path):
    from intelligence.news.pipeline import refresh_ticker_news
    from intelligence.news.sentiment import FinancialHeadlineCalibrationModel

    retrieved_at = datetime(2026, 9, 20, tzinfo=timezone.utc)
    checked_at = datetime(2026, 9, 24, tzinfo=timezone.utc)
    stale_sentiment = SentimentResult(
        SentimentLabel.NEUTRAL, .15, .70, .15, .70,
        "lexicon_fallback", "financial-lexicon", "v1", retrieved_at,
    )
    cached = NewsItem(
        "fpt-contract", "cafef_ticker", "https://cafef.vn/fpt-contract.chn",
        retrieved_at, "FPT lập kỷ lục ngành CNTT Việt Nam: Hơn 1,5 tỷ USD hợp đồng mới",
        tickers=("FPT",), primary_ticker="FPT", sentiment=stale_sentiment,
        retrieved_at=retrieved_at,
    )
    repository = SQLiteNewsRepository(tmp_path / "news.db")
    repository.save(cached)

    class EmptyProvider:
        def fetch(self, *args, **kwargs):
            return ()

    model = FinancialHeadlineCalibrationModel(
        LexiconSentimentModel(backend="lexicon_fallback", now=lambda: checked_at)
    )
    refresh_ticker_news(
        "FPT", repository=repository, sentiment_model=model,
        provider=EmptyProvider(), now=checked_at,
    )

    refreshed = repository.get(cached.id)
    assert refreshed.sentiment.label == SentimentLabel.POSITIVE
    assert refreshed.sentiment.calibration_version == "vn-financial-headline-v1"
    assert refreshed.retrieved_at == retrieved_at


def test_targeted_news_worker_enqueues_and_processes(tmp_path):
    import time
    from runtime.news_refresh import TargetedNewsWorker
    from intelligence.news.pipeline import CafeFTickerNewsProvider

    html_sample = """
    <div id="divEvents">
        <p>19/09/2026 <a href="/du-lieu/VIC-1.chn">VIC: Công bố báo cáo tài chính quý</a></p>
    </div>
    """
    class FakeResponse:
        text = html_sample
        def raise_for_status(self): pass

    db_path = tmp_path / "news.db"
    model = LexiconSentimentModel(now=lambda: NOW)
    prov = CafeFTickerNewsProvider(request_get=lambda *a, **kw: FakeResponse())

    worker = TargetedNewsWorker(
        repository_factory=lambda: SQLiteNewsRepository(db_path),
        sentiment_factory=lambda: model,
        provider_factory=lambda: prov,
        request_cooldown_seconds=60.0,
    )
    worker.start()
    try:
        # First request succeeds
        assert worker.request("VIC") is True
        # Immediate duplicate request rejected by cooldown/pending
        assert worker.request("VIC") is False

        # Wait briefly for worker thread to process queue
        main_repo = SQLiteNewsRepository(db_path)
        service = SentimentQueryService(main_repo)
        for _ in range(40):
            if len(service.latest_news("VIC", now=NOW)) > 0:
                break
            time.sleep(0.05)

        vic_news = service.latest_news("VIC", now=NOW)
        assert len(vic_news) == 1
        assert vic_news[0].primary_ticker == "VIC"
    finally:
        worker.stop(timeout=5.0)


def test_ticker_page_worker_records_provider_failure_as_error(tmp_path):
    import time
    from data.database import connect_database
    from data.migrations import bootstrap_schema
    from fundamentals.coverage_store import load_coverage
    from intelligence.news.pipeline import NewsProviderFetchError
    from runtime.news_refresh import TargetedNewsWorker

    coverage_path = tmp_path / "coverage.sqlite3"
    news_path = tmp_path / "news.sqlite3"

    def coverage_connection():
        connection = connect_database(f"sqlite:///{coverage_path.as_posix()}")
        bootstrap_schema(connection)
        return connection

    class BrokenProvider:
        def fetch(self, *args, **kwargs):
            raise NewsProviderFetchError("CafeF ticker page request failed (HTTPError)")

    worker = TargetedNewsWorker(
        repository_factory=lambda: SQLiteNewsRepository(news_path),
        sentiment_factory=lambda: LexiconSentimentModel(now=lambda: NOW),
        provider_factory=BrokenProvider,
        connection_factory=coverage_connection,
    )
    worker.start()
    try:
        assert worker.request("VIC") is True
        status = None
        for _ in range(100):
            connection = coverage_connection()
            try:
                status = load_coverage(connection, "VIC", "NEWS")
            finally:
                connection.close()
            if status is not None and status.status == "ERROR":
                break
            time.sleep(0.02)
        assert status is not None and status.status == "ERROR"
        assert status.provider_source == "ticker_page"
        assert "ticker-page refresh failed" in (status.error_reason or "")
    finally:
        worker.stop(timeout=2.0)
        worker.close()


def test_ticker_page_queue_claims_symbols_and_reports_saturation(tmp_path):
    import threading
    from queue import Queue
    from data.database import connect_database
    from data.migrations import bootstrap_schema
    from fundamentals.coverage_store import load_coverage
    from runtime.news_refresh import TargetedNewsWorker

    coverage_path = tmp_path / "coverage.sqlite3"
    news_path = tmp_path / "news.sqlite3"

    def coverage_connection():
        connection = connect_database(f"sqlite:///{coverage_path.as_posix()}")
        bootstrap_schema(connection)
        return connection

    entered_provider = threading.Event()
    release_provider = threading.Event()

    class BlockingProvider:
        def fetch(self, *args, **kwargs):
            entered_provider.set()
            assert release_provider.wait(2)
            return ()

    worker = TargetedNewsWorker(
        repository_factory=lambda: SQLiteNewsRepository(news_path),
        sentiment_factory=lambda: LexiconSentimentModel(now=lambda: NOW),
        provider_factory=BlockingProvider,
        connection_factory=coverage_connection,
    )
    worker._queue = Queue(maxsize=1)
    worker.start()
    try:
        assert worker.request("BLOCK") is True
        assert entered_provider.wait(2)

        connection = coverage_connection()
        try:
            assert load_coverage(connection, "BLOCK", "NEWS").status == "IN_PROGRESS"
        finally:
            connection.close()

        assert worker.request("QUEUED") is True
        assert worker.request("DEFERRED") is False
        connection = coverage_connection()
        try:
            deferred = load_coverage(connection, "DEFERRED", "NEWS")
        finally:
            connection.close()
        assert deferred is not None and deferred.status == "ERROR"
        assert "queue is full" in (deferred.error_reason or "")
    finally:
        release_provider.set()
        worker.stop(timeout=2.0)
        worker.close()


def test_ticker_page_startup_failure_closes_accepted_coverage_claim(tmp_path):
    import threading
    import time
    from data.database import connect_database
    from data.migrations import bootstrap_schema
    from fundamentals.coverage_store import load_coverage
    from runtime.news_refresh import TargetedNewsWorker

    coverage_path = tmp_path / "coverage.sqlite3"
    initializing = threading.Event()
    release_startup = threading.Event()

    def coverage_connection():
        connection = connect_database(f"sqlite:///{coverage_path.as_posix()}")
        bootstrap_schema(connection)
        return connection

    def fail_repository_startup():
        initializing.set()
        assert release_startup.wait(2)
        raise RuntimeError("news database unavailable")

    worker = TargetedNewsWorker(
        repository_factory=fail_repository_startup,
        sentiment_factory=lambda: LexiconSentimentModel(now=lambda: NOW),
        connection_factory=coverage_connection,
    )
    worker.start()
    try:
        assert initializing.wait(2)
        assert worker.request("FAIL") is True
        release_startup.set()

        status = None
        for _ in range(100):
            connection = coverage_connection()
            try:
                status = load_coverage(connection, "FAIL", "NEWS")
            finally:
                connection.close()
            if status is not None and status.status == "ERROR":
                break
            time.sleep(0.02)
        assert status is not None and status.status == "ERROR"
        assert "worker initialization failed" in (status.error_reason or "")
    finally:
        release_startup.set()
        worker.stop(timeout=2.0)
        worker.close()

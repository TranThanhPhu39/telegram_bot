"""Investor-facing dashboard behaviour: sections, honesty and graceful gaps."""

from datetime import date, datetime, timedelta, timezone

import pytest

from asmf_data.models import FinancialReport, SectorMembership
from asmf_data.store import upsert_financial_reports, upsert_sector_memberships
from data.database import connect_database
from intelligence.news.service import SentimentAggregate
from runtime.analysis import describe_freshness, interpret_indicators
from runtime.bot_service import RuntimeBotDataService
from runtime.views import Freshness
from scanner.universe import ScannerInstrument
from telegram_bot.commands import TelegramCommandService
from telegram_bot.formatters import format_stock_overview, format_technical

NOW = 1_800_000_000
UTC = timezone.utc


def payload(symbol="FPT", count=260, base=100.0):
    timestamps = [NOW - (count - index) * 86_400 for index in range(count)]
    closes = [round(base + index * 0.5, 2) for index in range(count)]
    return {
        "symbol": symbol,
        "t": [str(value) for value in timestamps],
        "o": closes,
        "h": [round(value + 1, 2) for value in closes],
        "l": [round(value - 1, 2) for value in closes],
        "c": closes,
        "v": [100_000.0 + index * 10 for index in range(count)],
    }


class FakeClient:
    def __init__(self, count=260):
        self.count = count
        self.fail = False
        self.calls = []

    def get_gap_chart(self, symbols, **kwargs):
        self.calls.append(tuple(symbols))
        if self.fail:
            raise ValueError("offline")
        return [
            payload(symbol, self.count, base=1000.0 if symbol == "VNINDEX" else 100.0)
            for symbol in symbols
        ]


class NoNews:
    def latest_news(self, *args, **kwargs):
        return ()

    def ticker_sentiment(self, *args, **kwargs):
        return None

    def severe_negative(self, *args, **kwargs):
        return None


class PositiveNews(NoNews):
    def ticker_sentiment(self, ticker, hours=24, **kwargs):
        return SentimentAggregate(
            ticker.upper(), hours, 0.92, 9, 9, 0, 0, 0.95,
            ("EARNINGS",), datetime.now(UTC), ("phobert",),
        )


def service(client=None, news=None, count=260):
    return RuntimeBotDataService(
        client or FakeClient(count),
        connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        news_service=news,
        now=lambda: NOW,
    )


def add_fundamentals(runtime, symbol="FPT"):
    rows = []
    for index in range(8):
        year, quarter = 2025 + index // 4, index % 4 + 1
        rows.append(
            FinancialReport(
                symbol, f"{year}Q{quarter}", date(year, quarter * 3, 28), True,
                1_000.0 + index * 100, 100.0 + index * 20, 5_000.0, 2_000.0,
                "Vietstock consolidated",
            )
        )
    upsert_financial_reports(runtime.connection, rows)


# ---------------------------------------------------------------- /soi

def test_soi_renders_every_supported_section() -> None:
    runtime = service(news=PositiveNews())
    add_fundamentals(runtime)
    text = runtime.symbol_overview("FPT")
    for marker in ("GIÁ", "KỸ THUẬT", "HỖ TRỢ / KHÁNG CỰ", "THỊ TRƯỜNG",
                   "Chiến lược CL1", "CƠ BẢN", "SENTIMENT", "DỮ LIỆU"):
        assert marker in text
    assert "Phiên dữ liệu" not in text or "Dữ liệu phiên" in text


def test_soi_stays_compact_for_telegram() -> None:
    runtime = service(news=PositiveNews())
    add_fundamentals(runtime)
    text = runtime.symbol_overview("FPT")
    assert len(text) < 2_600
    assert len(text.splitlines()) < 70


def test_soi_without_fundamentals_does_not_fabricate_metrics() -> None:
    text = service().symbol_overview("FPT")
    assert "Chưa có dữ liệu cơ bản point-in-time" in text
    assert "P/E" not in text


def test_fundamental_view_marks_noncontiguous_quarters_insufficient() -> None:
    runtime = service()
    periods = (
        "2026Q2", "2026Q1", "2025Q4", "2025Q2",
        "2025Q1", "2024Q4", "2024Q3", "2024Q2",
    )
    upsert_financial_reports(runtime.connection, [
        FinancialReport(
            "FPT", period, date(2026, 9, 1), True,
            1_000.0, 100.0, 5_000.0, 2_000.0, "TEST",
        )
        for period in periods
    ])

    text = runtime.fundamental_overview("FPT")

    assert "🧾 CƠ BẢN: INSUFFICIENT" in text
    assert "Chưa đủ 8 quý liên tục để tính TTM. Thiếu: 2025Q3." in text
    assert "• Tăng trưởng doanh thu (TTM):" not in text
    assert "• Tăng trưởng LNST (TTM):" not in text


def test_soi_without_sentiment_module_states_unavailable() -> None:
    assert "News sentiment unavailable." in service().symbol_overview("FPT")


def test_soi_with_empty_news_window_is_not_reported_as_unavailable() -> None:
    text = service(news=NoNews()).symbol_overview("FPT")
    assert "Không có tin trong cửa sổ theo dõi." in text


def test_provider_failure_labels_cached_sqlite_data() -> None:
    client = FakeClient()
    runtime = service(client)
    runtime.symbol_overview("FPT")
    client.fail = True
    text = runtime.symbol_overview("FPT")
    assert "SQLite cache" in text
    assert "cached/EOD" in text


def test_missing_history_returns_message_not_stack_trace() -> None:
    client = FakeClient()
    client.fail = True
    text = service(client).symbol_overview("FPT")
    assert "Chưa có dữ liệu lịch sử cho FPT" in text
    assert "Traceback" not in text and "None" not in text


# ---------------------------------------------------------------- /why

def test_why_gives_indicator_meaning_and_implication() -> None:
    text = service().signal_explanation("FPT")
    assert "VÌ SAO" in text
    assert "→" in text
    assert "Điều kiện cần theo dõi" in text
    assert "Bối cảnh thị trường" in text
    assert "Giới hạn dữ liệu" in text
    assert "khuyến nghị" in text


def test_interpretation_never_turns_rsi_into_an_order() -> None:
    runtime = service()
    view = runtime.stock_analysis("FPT")
    lines = interpret_indicators(view.technical)
    rsi_line = next(line for line in lines if line.startswith("RSI14"))
    assert "→" in rsi_line
    assert "MUA" not in rsi_line.upper().replace("KHÔNG TỰ ĐỘNG", "")


# ---------------------------------------------------------------- /market

def test_market_reports_regime_and_explicit_unavailable_sections() -> None:
    text = service().market_overview()
    assert "VNINDEX" in text
    assert "REGIME:" in text
    assert "BREADTH: unavailable" in text
    assert "LIQUIDITY: unavailable" in text


def test_market_without_breadth_never_claims_a_complete_regime() -> None:
    text = service().market_overview()
    assert "chưa có breadth" in text


# ------------------------------------------------------- data freshness

@pytest.mark.parametrize(
    "age_days, expected",
    [(0, Freshness.EOD_TODAY), (2, Freshness.EOD), (30, Freshness.STALE)],
)
def test_freshness_is_derived_from_the_session_date(age_days, expected) -> None:
    timestamp = NOW - age_days * 86_400
    freshness, staleness = describe_freshness(timestamp, NOW, cached=False)
    assert freshness is expected
    assert staleness == age_days


def test_unavailable_history_is_labelled_unavailable() -> None:
    assert describe_freshness(None, NOW, cached=True) == (Freshness.UNAVAILABLE, None)


def test_soi_shows_session_and_source_provenance() -> None:
    runtime = service()
    add_fundamentals(runtime)
    text = runtime.symbol_overview("FPT")
    assert "Phiên dữ liệu:" in text
    assert "Nguồn: Vietcap historical" in text
    assert "Nguồn BCTC: Vietstock consolidated" in text


def test_fundamental_command_shows_as_of_and_period() -> None:
    runtime = service()
    add_fundamentals(runtime)
    text = runtime.fundamental_overview("FPT")
    assert "Kỳ báo cáo: 2026Q4" in text
    assert "As-of: 2026-12-28" in text
    assert "ROE (TTM)" in text


def test_fundamental_command_without_data_is_explicit() -> None:
    assert "Fundamental data missing." in service().fundamental_overview("FPT")


# ------------------------------------------------------------- strategy

def test_strategy_block_lists_positive_negative_and_evidence_coverage() -> None:
    text = service().symbol_overview("FPT")
    assert "Độ phủ bằng chứng:" in text
    assert "Chưa đạt:" in text
    assert "%" not in text.split("Độ phủ bằng chứng:")[1].split("\n")[0]


def test_asmf_missing_layer_blocks_buy_and_is_shown() -> None:
    runtime = service()
    text = runtime.symbol_overview("FPT", "ASMF")
    assert "Chiến lược ASMF" in text
    assert "CHƯA ĐỦ ĐIỀU KIỆN" in text
    assert "Sector=MISSING" in text
    assert "Fundamental=MISSING" in text
    assert "Institutional=" not in text


def test_positive_sentiment_alone_never_produces_buy() -> None:
    runtime = service(news=PositiveNews())
    text = runtime.symbol_overview("FPT", "ASMF")
    assert "Sentiment=SUPPORTIVE" in text
    assert "CHƯA ĐỦ ĐIỀU KIỆN" in text
    assert "MUA" not in text.split("🎯")[1].split("\n")[0]


def test_technical_command_exposes_levels_with_reasons() -> None:
    text = service().technical_overview("FPT")
    assert "HỖ TRỢ / KHÁNG CỰ" in text
    assert "đỉnh 20 phiên trước đó" in text
    assert "ATR14" in text


# ------------------------------------------------------------- scanner

def test_scan_explains_why_each_symbol_is_listed() -> None:
    runtime = service()
    runtime.symbol_overview("FPT")
    text = runtime.scan_overview()
    assert "KẾT QUẢ QUÉT" in text
    assert "1. FPT" in text
    assert "RS" in text
    assert "CB " in text
    assert "Vũ trụ:" in text and "Hiển thị: Top" in text
    assert "🕒" in text


def test_scan_results_tuple_contract_is_preserved() -> None:
    assert service().scan_results() == ("FPT",)


# --------------------------------------------------------------- sector

def test_sector_without_member_history_reports_missing_not_fabricated() -> None:
    runtime = service()
    upsert_sector_memberships(runtime.connection, [
        SectorMembership(symbol, "8300", "Banks", date(2020, 1, 1), None, "Vietcap")
        for symbol in ("FPT", "AAA", "BBB")
    ])
    text = runtime.sector_overview("FPT")
    assert "NGÀNH 8300" in text
    assert "Thiếu dữ liệu:" in text
    assert "Dẫn dắt" not in text


def test_unknown_sector_is_reported_cleanly() -> None:
    assert "Không có dữ liệu ngành" in service().sector_overview("ZZZ")


# ----------------------------------------------------- command surface

class LegacyService:
    """A data service predating the drill-down commands."""

    def symbol_overview(self, symbol, strategy="CL1"):
        return "LEGACY"

    def scan_results(self):
        return ("FPT",)

    def market_overview(self):
        return "MARKET"

    def signal_explanation(self, symbol):
        return "WHY"

    def performance_overview(self):
        return "PERF"

    def strategy_catalog(self):
        return "CL1, ASMF"

    def latest_news(self, symbol):
        return "NEWS"

    def sentiment_overview(self, symbol):
        return "SENT"


def test_legacy_data_service_keeps_working() -> None:
    commands = TelegramCommandService(LegacyService())
    assert commands.soi(["fpt"]) == "LEGACY"
    assert commands.scan() == "Watchlist: FPT"
    assert commands.technical(["fpt"]).startswith("Tính năng này chưa")
    assert commands.sector(["fpt"]).startswith("Tính năng này chưa")


def test_new_commands_reach_the_runtime_service() -> None:
    commands = TelegramCommandService(service())
    assert "KỸ THUẬT" in commands.technical(["fpt"])
    assert "CƠ BẢN" in commands.fundamental(["fpt"])
    assert "KẾT QUẢ QUÉT" in commands.scan() or "Chưa có mã" in commands.scan()


def test_usage_errors_are_raised_not_crashed() -> None:
    commands = TelegramCommandService(service())
    with pytest.raises(ValueError):
        commands.technical([])
    with pytest.raises(ValueError):
        commands.fundamental(["A B"])


# ------------------------------------------------------------ formatter

def test_formatter_never_crashes_on_empty_view() -> None:
    from runtime.views import DataQualityView, StockAnalysisView

    view = StockAnalysisView(
        symbol="XXX", price=None, technical=None, market=None, strategy=None,
        fundamental=None, sentiment=None,
        data_quality=DataQualityView(
            Freshness.UNAVAILABLE, None, None, "Vietcap/SQLite đều không có dữ liệu"
        ),
    )
    assert "XXX" in format_stock_overview(view)
    assert "Chưa đủ dữ liệu kỹ thuật cho XXX." == format_technical(view)


def test_short_history_degrades_without_raising() -> None:
    runtime = service(FakeClient(count=40))
    text = runtime.symbol_overview("FPT")
    assert "Chưa đủ dữ liệu" in text
    assert "N/A" in text


# ------------------------------------------------------------ Issue 7 tests

def test_soi_renders_compact_sentiment() -> None:
    runtime = service(news=PositiveNews())
    add_fundamentals(runtime)
    text = runtime.symbol_overview("FPT")
    assert "📰 SENTIMENT\nPositive | score +0.92 | 9 bài\nTin mới nhất:" in text
    assert "P/N/N:" not in text
    assert "model confidence 0.95" not in text


def test_format_sentiment_shows_aggregate_only_no_article_urls_or_titles() -> None:
    from runtime.views import SentimentView
    from telegram_bot.formatters import format_sentiment

    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    view = SentimentView(
        available=True,
        label="Negative",
        score=-0.18,
        model_confidence=0.55,
        article_count=2,
        positive_count=1,
        neutral_count=3,
        negative_count=1,
        top_events=("EARNINGS", "DIVIDEND"),
        latest_at=now,
        backends=("phobert",),
    )
    text = format_sentiment("FPT", view)
    assert "🧠 FPT — SENTIMENT" in text
    assert "🟡 TRUNG LẬP, HƠI NGHIÊNG TIÊU CỰC" in text
    assert "Score: -0.18" in text
    assert "Độ tin cậy: TRUNG BÌNH" in text
    assert "Tích cực: 1" in text
    assert "Trung lập: 3" in text
    assert "Tiêu cực: 1" in text
    assert "• KQKD" in text
    assert "⚠️ Chỉ tìm được 2/5 tin trong 30 ngày" in text
    assert "độ phủ dữ liệu thấp" in text
    assert "chưa đủ mạnh để tự tạo tín hiệu giao dịch" in text
    assert "/tin FPT để xem bài gốc." in text
    # No per-article titles or URLs -- that content lives only in /tin now.
    assert "https://" not in text
    assert "Chi tiết bài viết" not in text


def test_sentiment_overview_end_to_end(tmp_path) -> None:
    from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
    from intelligence.news.repository import SQLiteNewsRepository
    from intelligence.news.service import SentimentQueryService

    repo = SQLiteNewsRepository(str(tmp_path / "news.db"))
    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    item = NewsItem(
        id="news_1",
        source="CafeF",
        url="https://s.cafef.vn/fpt-123.chn",
        published_at=now,
        title="FPT ký hợp đồng lớn",
        tickers=("FPT",),
        primary_ticker="FPT",
        sentiment=SentimentResult(
            label=SentimentLabel.POSITIVE,
            probability_positive=0.9,
            probability_neutral=0.1,
            probability_negative=0.0,
            model_confidence=0.95,
            backend="phobert",
            model_name="phobert-base",
            model_version="1.0",
            analyzed_at=now,
        ),
    )
    repo.save(item)
    news_svc = SentimentQueryService(repo, 24.0)

    runtime = service(news=news_svc)
    text = runtime.sentiment_overview("FPT")
    assert "🧠 FPT — SENTIMENT" in text
    # Only 1 article in a 30-day/5-article target window -- low coverage, so the
    # strong 🟢 bucket is softened to 🟡 with a low-confidence qualifier.
    assert "🟡 TÍCH CỰC (độ tin cậy thấp)" in text
    assert "🟢 TÍCH CỰC" not in text
    assert "/tin FPT để xem bài gốc." in text
    assert "⚠️ Chỉ tìm được 1/5 tin trong 30 ngày" in text
    assert "https://s.cafef.vn" not in text
    assert "FPT ký hợp đồng lớn" not in text


def test_format_sentiment_softens_strong_bucket_on_low_coverage() -> None:
    """A single very negative article should not render as a bold 🔴 verdict."""
    from runtime.views import SentimentView
    from telegram_bot.formatters import format_sentiment

    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    view = SentimentView(
        available=True,
        label="Negative",
        score=-0.72,
        model_confidence=0.63,
        article_count=1,
        positive_count=0,
        neutral_count=0,
        negative_count=1,
        top_events=("EARNINGS",),
        latest_at=now,
        backends=("phobert",),
    )
    text = format_sentiment("XYZ", view)
    assert "🟡 TIÊU CỰC (độ tin cậy thấp)" in text
    assert "🔴 TIÊU CỰC" not in text
    assert "chưa đủ mạnh để tự tạo tín hiệu giao dịch" in text


def test_format_sentiment_keeps_strong_bucket_when_coverage_and_confidence_high() -> None:
    """With enough articles and high confidence, the bold bucket stays as-is."""
    from runtime.views import SentimentView
    from telegram_bot.formatters import format_sentiment

    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    view = SentimentView(
        available=True,
        label="Negative",
        score=-0.6,
        model_confidence=0.85,
        article_count=6,
        positive_count=0,
        neutral_count=1,
        negative_count=5,
        top_events=("EARNINGS",),
        latest_at=now,
        backends=("phobert",),
    )
    text = format_sentiment("XYZ", view)
    assert "🔴 TIÊU CỰC" in text
    assert "độ tin cậy thấp" not in text


def test_format_sentiment_no_coverage_warning_when_target_met() -> None:
    from runtime.views import SentimentView
    from telegram_bot.formatters import format_sentiment

    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    view = SentimentView(
        available=True,
        label="Positive",
        score=0.5,
        model_confidence=0.8,
        article_count=7,
        positive_count=4,
        neutral_count=3,
        negative_count=0,
        top_events=("OTHER",),
        latest_at=now,
        backends=("lexicon",),
    )
    text = format_sentiment("TCB", view)
    assert "🟢 TÍCH CỰC" in text
    assert "• KHÁC" in text
    assert "⚠️" not in text
    assert "độ phủ dữ liệu thấp" not in text
    assert "Sentiment là yếu tố tham khảo, không tự tạo tín hiệu giao dịch." in text


def test_callback_sent_renders_aggregate_sentiment() -> None:
    from telegram_bot.app import render_callback

    runtime = service(news=PositiveNews())
    commands = TelegramCommandService(runtime)
    text = render_callback(commands, "sent", "FPT")
    assert "🧠 FPT — SENTIMENT" in text
    assert "🟢 TÍCH CỰC" in text
    assert "/tin FPT để xem bài gốc." in text


def test_soi_compact_sentiment_various_states() -> None:
    from runtime.views import SentimentView
    from telegram_bot.formatters import _sentiment_block

    now = datetime(2026, 9, 21, 10, 50, tzinfo=timezone.utc)
    # 1. Available
    v1 = SentimentView(available=True, label="Negative", score=-0.43, article_count=2, latest_at=now)
    out1 = _sentiment_block(v1, compact=True)
    assert out1 == "📰 SENTIMENT\nNegative | score -0.43 | 2 bài\nTin mới nhất: 21/09 17:50"
    assert "P/N/N" not in out1
    assert "model confidence" not in out1

    # 2. Unavailable with note
    v2 = SentimentView(available=False, note="Không có tin trong cửa sổ theo dõi.")
    out2 = _sentiment_block(v2, compact=True)
    assert out2 == "📰 SENTIMENT\nKhông có tin trong cửa sổ theo dõi."

    # 3. Unavailable default
    v3 = SentimentView(available=False)
    out3 = _sentiment_block(v3, compact=True)
    assert out3 == "📰 SENTIMENT\nNews sentiment unavailable."


def test_build_risk_items_removes_24h_wording() -> None:
    from runtime.analysis import build_risk_items
    from runtime.views import SentimentView

    negative_sentiment = SentimentView(
        available=True,
        label="Negative",
        score=-0.45,
        article_count=3,
    )
    risks, watch = build_risk_items(
        technical=None,
        market=None,
        strategy=None,
        sentiment=negative_sentiment,
    )
    assert len(risks) == 1
    assert "24h" not in risks[0]
    assert "24 giờ" not in risks[0]
    assert risks[0] == "Sentiment tin tức âm (-0.45); đây là context, không phải lệnh bán"



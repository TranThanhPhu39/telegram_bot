"""Live verification test script for Issue 8:
- Verify complete removal of stale "24h" and "24 giờ" wording from HELP_TEXT and command handlers.
- Verify negative sentiment risk item produces "Sentiment tin tức âm (...)" without "24h".
- Verify live /help, /start, /soi, /sentiment on real SQLite databases have zero occurrences of stale "24h" wording.
"""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.database import connect_database
from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.service import SentimentQueryService
from runtime.analysis import build_risk_items
from runtime.bot_service import RuntimeBotDataService
from runtime.views import SentimentView
from scanner.universe import ScannerInstrument
from telegram_bot.commands import HELP_TEXT, TelegramCommandService


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=================================================================")
    print("LIVE VERIFICATION: ISSUE 8 (Complete Removal of '24h' Wording)")
    print("=================================================================")

    # -------------------------------------------------------------
    # Check 1: HELP_TEXT and Command Service Help / Start
    # -------------------------------------------------------------
    print("\n1. Auditing HELP_TEXT and /help, /start outputs:")
    assert "24 giờ" not in HELP_TEXT, "Stale '24 giờ' found in HELP_TEXT!"
    assert "24h" not in HELP_TEXT, "Stale '24h' found in HELP_TEXT!"
    assert "24 tiếng" not in HELP_TEXT, "Stale '24 tiếng' found in HELP_TEXT!"
    assert "/sentiment FPT - sentiment tin tức gần đây (tối đa 30 ngày)" in HELP_TEXT, (
        "Missing updated /sentiment description in HELP_TEXT"
    )
    print("   [OK] HELP_TEXT verified clean of '24h' and '24 giờ'.")

    repo = SQLiteNewsRepository("news_sentiment.db")
    news_svc = SentimentQueryService(repo, half_life_hours=24.0)
    db_conn = connect_database("sqlite:///market.db")

    class DummyClient:
        def get_gap_chart(self, symbols, **kwargs):
            return []

    service = RuntimeBotDataService(
        DummyClient(),
        db_conn,
        (ScannerInstrument("HC1", "HNX", "STOCK"), ScannerInstrument("FPT", "HOSE", "STOCK")),
        news_service=news_svc,
    )
    commands = TelegramCommandService(service)

    help_out = commands.help()
    start_out = commands.start()
    assert "24 giờ" not in help_out, "Stale '24 giờ' found in commands.help()!"
    assert "24h" not in help_out, "Stale '24h' found in commands.help()!"
    assert "24 giờ" not in start_out, "Stale '24 giờ' found in commands.start()!"
    assert "24h" not in start_out, "Stale '24h' found in commands.start()!"
    print("   [OK] commands.help() and commands.start() verified clean.")

    # -------------------------------------------------------------
    # Check 2: build_risk_items Negative Sentiment Risk Flag
    # -------------------------------------------------------------
    print("\n2. Auditing build_risk_items with negative sentiment:")
    neg_view = SentimentView(
        available=True,
        label="Negative",
        score=-0.42,
        article_count=3,
    )
    risks, watch = build_risk_items(
        technical=None,
        market=None,
        strategy=None,
        sentiment=neg_view,
    )
    print(f"   Generated risks: {risks}")
    assert len(risks) == 1
    assert "24h" not in risks[0], f"Stale '24h' found in risk item: {risks[0]}"
    assert "24 giờ" not in risks[0], f"Stale '24 giờ' found in risk item: {risks[0]}"
    assert risks[0] == "Sentiment tin tức âm (-0.42); đây là context, không phải lệnh bán", (
        f"Unexpected risk item text: {risks[0]}"
    )
    print("   [OK] Negative sentiment risk item is strictly 'Sentiment tin tức âm (-0.42)...'")

    # -------------------------------------------------------------
    # Check 3: Full live /soi and /sentiment on real DB
    # -------------------------------------------------------------
    print("\n3. Testing live /sentiment and /soi outputs for real tickers (HC1, FPT):")
    for sym in ("HC1", "FPT"):
        sent_output = commands.sentiment([sym])
        print(f"\n--- /sentiment {sym} Header Preview ---")
        first_line = sent_output.splitlines()[0]
        print(f"   {first_line}")
        assert "24h" not in sent_output, f"Stale '24h' found in /sentiment {sym}!"
        assert "24 giờ" not in sent_output, f"Stale '24 giờ' found in /sentiment {sym}!"
        print(f"   [OK] /sentiment {sym} is 100% free of '24h' / '24 giờ'.")

    # -------------------------------------------------------------
    # Check 4: Live /soi with simulated negative sentiment
    # -------------------------------------------------------------
    print("\n4. Testing /soi dashboard output with negative sentiment:")
    now_ts = 1758500000
    def make_payload(sym, count=60, base=100.0):
        t = [str(now_ts - (count - i) * 86400) for i in range(count)]
        c = [round(base + i * 0.2, 2) for i in range(count)]
        return {
            "symbol": sym, "t": t, "o": c, "h": [x + 1 for x in c],
            "l": [x - 1 for x in c], "c": c, "v": [50000.0] * count,
        }

    class ClientWithBars:
        def get_gap_chart(self, symbols, **kwargs):
            return [
                make_payload(s, 60, base=1200.0 if s == "VNINDEX" else 25.0)
                for s in symbols
            ]

    class NegativeNewsService:
        def ticker_sentiment(self, ticker, **kwargs):
            from intelligence.news.service import SentimentAggregate
            from datetime import datetime, timezone
            return SentimentAggregate(
                ticker=ticker,
                hours=720,
                score=-0.55,
                article_count=4,
                positive_count=0,
                neutral_count=1,
                negative_count=3,
                model_confidence=0.88,
                top_events=("MARKET",),
                latest_at=datetime.now(timezone.utc),
                backends=("phobert",),
                articles=(),
            )

        def latest_news(self, ticker, limit=5):
            return []

    service_with_neg_news = RuntimeBotDataService(
        ClientWithBars(),
        db_conn,
        (ScannerInstrument("HC1", "HNX", "STOCK"),),
        news_service=NegativeNewsService(),
    )
    soi_text = service_with_neg_news.symbol_overview("HC1")
    assert soi_text is not None, "Expected /soi HC1 to return text"
    print("\n--- /soi HC1 (with negative sentiment) Output Snippet ---")
    for line in soi_text.splitlines():
        if "Sentiment" in line or "tin tức" in line or "⚠️" in line:
            print(f"   {line}")
    assert "24h" not in soi_text, f"Stale '24h' found in /soi HC1: {soi_text}"
    assert "24 giờ" not in soi_text, f"Stale '24 giờ' found in /soi HC1: {soi_text}"
    assert "Sentiment tin tức âm (-0.55); đây là context, không phải lệnh bán" in soi_text, (
        f"Expected updated risk item in /soi output! Got:\n{soi_text}"
    )
    print("   [OK] Live /soi with negative news rendered updated risk flag without '24h'.")

    print("\n=================================================================")
    print("ALL ISSUE 8 LIVE AUDIT & INTEGRATION CHECKS PASSED (100% GREEN)!")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())

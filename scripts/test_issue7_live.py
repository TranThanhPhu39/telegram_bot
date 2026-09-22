"""Live verification test script for Issue 7:
- /soi compact sentiment summary
- /sentiment article-level output with clickable URLs
- Telegram callback sent:<SYM>
"""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.database import connect_database
from intelligence.news.pipeline import refresh_ticker_news
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import build_sentiment_model
from intelligence.news.service import SentimentQueryService
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument
from telegram_bot.app import render_callback
from telegram_bot.commands import TelegramCommandService
from telegram_bot.formatters import _sentiment_block


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=================================================================")
    print("LIVE VERIFICATION: ISSUE 7 (Sentiment Compact & Article Output)")
    print("=================================================================")

    repo = SQLiteNewsRepository("news_sentiment.db")
    model = build_sentiment_model()

    print("\n1. Crawling live corporate news from CafeF for HC1 & FPT...")
    for sym in ("HC1", "FPT"):
        count = refresh_ticker_news(sym, repository=repo, sentiment_model=model, limit=5, max_age_days=30)
        print(f"   [OK] Live crawl {sym}: {count} articles processed")

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

    # -------------------------------------------------------------
    # Test 1: /soi compact sentiment block
    # -------------------------------------------------------------
    print("\n2. Testing /soi Compact Sentiment Summary:")
    for sym in ("HC1", "FPT"):
        s_view = service._sentiment_view(sym)
        block = _sentiment_block(s_view, compact=True)
        lines = block.strip().splitlines()
        print(f"\n--- /soi {sym} Sentiment Block ---")
        print(block)

        assert lines[0] == "📰 SENTIMENT", f"Expected header '📰 SENTIMENT', got '{lines[0]}'"
        assert "score" in lines[1] and "bài" in lines[1], f"Line 2 missing score/bài: {lines[1]}"
        assert "Tin mới nhất:" in lines[2], f"Line 3 missing 'Tin mới nhất:': {lines[2]}"
        assert len(lines) == 3, f"Expected exactly 3 lines in compact summary, got {len(lines)}"
        assert "model confidence" not in block, "Compact summary must not show model confidence"
        assert "P/N/N" not in block, "Compact summary must not show P/N/N"
        assert "sự kiện:" not in block, "Compact summary must not show top events"
        print(f"   [PASS] /soi {sym} compact summary is exactly 3 lines, clean & no clutter.")

    # -------------------------------------------------------------
    # Test 2: /sentiment command article-level output + clickable URLs
    # -------------------------------------------------------------
    print("\n3. Testing /sentiment Detailed Article-Level Output:")
    sent_text = service.sentiment_overview("HC1")
    print("\n--- /sentiment HC1 Output ---")
    print(sent_text)

    assert "📰 HC1 — SENTIMENT (5 TIN MỚI NHẤT / 30 NGÀY)" in sent_text
    assert "Nhãn tổng hợp:" in sent_text
    assert "Chi tiết bài viết:" in sent_text
    assert "1. " in sent_text, "Missing numbered article 1."
    assert "Thời gian:" in sent_text, "Missing published timestamp"
    assert "Nguồn:" in sent_text, "Missing news source"
    assert "Link: https://" in sent_text, "Missing direct clickable link"
    assert "](https://" in sent_text, "Missing markdown link syntax"
    assert "Sentiment là context; tự nó không tạo tín hiệu MUA." in sent_text
    print("   [PASS] /sentiment HC1 contains aggregate, numbered articles, safe markdown & clickable URLs.")

    # -------------------------------------------------------------
    # Test 3: Telegram Button Callback (sent:HC1)
    # -------------------------------------------------------------
    print("\n4. Testing Telegram Button Callback (sent:HC1):")
    cb_text = render_callback(commands, "sent", "HC1")
    assert cb_text == sent_text, "Callback 'sent:HC1' must match commands.sentiment(['HC1'])"
    print("   [PASS] Button callback 'sent:HC1' returns identical article-level view.")

    # -------------------------------------------------------------
    # Test 4: Graceful handling of ticker with 0 news (XYZ999)
    # -------------------------------------------------------------
    print("\n5. Testing ticker with NO news (XYZ999):")
    no_news_soi = _sentiment_block(service._sentiment_view("XYZ999"), compact=True)
    no_news_sent = service.sentiment_overview("XYZ999")
    print(f"   /soi XYZ999:\n   {no_news_soi.replace(chr(10), ' | ')}")
    print(f"   /sentiment XYZ999:\n   {no_news_sent.replace(chr(10), ' | ')}")
    assert "Không có tin trong cửa sổ theo dõi." in no_news_soi
    assert "Không có tin trong cửa sổ theo dõi." in no_news_sent
    print("   [PASS] Graceful fallback on missing news.")

    print("\n=================================================================")
    print("ALL LIVE VERIFICATION CHECKS PASSED WITH 100% SUCCESS!")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

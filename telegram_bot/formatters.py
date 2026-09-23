"""Telegram rendering for analysis views.

The formatter performs no computation and no data access.  It only renders what
a view already established, and it never crashes on ``None``: an unavailable
value is printed as an explicit unavailable marker.
"""

from __future__ import annotations

from datetime import timedelta, timezone
from typing import Sequence

from runtime.views import (
    Freshness,
    MarketContextView,
    NewsItemView,
    ScanRowView,
    SectorView,
    SentimentView,
    StockAnalysisView,
    TechnicalView,
)

VIETNAM_TIMEZONE = timezone(timedelta(hours=7))
UNAVAILABLE = "N/A"
DISCLAIMER = "Tín hiệu định lượng, không phải khuyến nghị đầu tư."

DIVIDER = "────────────────────────"
HEADER_DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━"


FRESHNESS_LABELS = {
    Freshness.REALTIME: "Realtime",
    Freshness.EOD_TODAY: "EOD (phiên gần nhất là hôm nay)",
    Freshness.EOD: "EOD (phiên đã đóng)",
    Freshness.STALE: "Cached/cũ",
    Freshness.UNAVAILABLE: "Không có dữ liệu",
}


def number(value: float | None, digits: int = 2) -> str:
    return UNAVAILABLE if value is None else f"{value:,.{digits}f}"


def integer(value: float | None) -> str:
    return UNAVAILABLE if value is None else f"{value:,.0f}"


def percent(value: float | None, digits: int = 2) -> str:
    return UNAVAILABLE if value is None else f"{value:+.{digits}f}%"


def format_stock_overview(view: StockAnalysisView, extra_blocks: Sequence[str] = ()) -> str:
    """Compact dashboard; drill-down lives in /technical, /fundamental, /why.

    ``extra_blocks`` are informational sections (e.g. portfolio context) that are
    appended before the data-quality block and never alter strategy output.
    """
    if view.error:
        return view.error
    blocks: list[str] = [f"📊 {view.symbol} — TỔNG QUAN\n{HEADER_DIVIDER}"]

    if view.price is not None:
        blocks.append(
            "💰 GIÁ\n"
            f"• Đóng cửa: {number(view.price.close)} ({percent(view.price.change_percent)})\n"
            f"• Khối lượng: {integer(view.price.volume)}\n"
            f"• Dữ liệu phiên: {view.price.session_date or UNAVAILABLE}"
        )

    if view.technical is not None:
        technical = view.technical
        trend_icon = "📈" if "TĂNG" in technical.trend else "📉" if "GIẢM" in technical.trend else "➡️"
        blocks.append(
            "📈 KỸ THUẬT\n"
            f"• Xu hướng: {trend_icon} {technical.trend}\n"
            f"• EMA20: {number(technical.ema20)} | EMA50: {number(technical.ema50)}\n"
            f"• RSI14: {number(technical.rsi14)} | ADX14: {number(technical.adx14)}\n"
            f"• KL/TB20: {_ratio(technical.volume_ratio)} | "
            f"RS vs VNINDEX: {percent(technical.relative_strength)}"
        )
        levels = _levels_block(technical)
        if levels:
            blocks.append(levels)

    if view.market is not None:
        blocks.append(_market_summary(view.market))

    if view.strategy is not None:
        blocks.append(_strategy_block(view.strategy))

    if view.fundamental is not None:
        blocks.append(_fundamental_block(view.fundamental, compact=True))

    if view.sentiment is not None:
        blocks.append(_sentiment_block(view.sentiment, compact=True))

    if view.risks or view.watch_items:
        lines = ["⚠️ RỦI RO / THEO DÕI"]
        lines.extend(f"• {item}" for item in view.risks[:3])
        lines.extend(f"→ {item}" for item in view.watch_items[:3])
        blocks.append("\n".join(lines))

    blocks.extend(block for block in extra_blocks if block)
    blocks.append(_data_quality_block(view))
    blocks.append(f"{DIVIDER}\n💡 Gõ /why {view.symbol} để xem giải thích chi tiết.\n⚠️ {DISCLAIMER}")
    return "\n\n".join(blocks)


def format_technical(view: StockAnalysisView) -> str:
    if view.error:
        return view.error
    if view.technical is None:
        return f"Chưa đủ dữ liệu kỹ thuật cho {view.symbol}."
    technical = view.technical
    trend_icon = "📈" if "TĂNG" in technical.trend else "📉" if "GIẢM" in technical.trend else "➡️"
    blocks = [
        f"📈 {view.symbol} — KỸ THUẬT\n{HEADER_DIVIDER}",
        (
            f"Xu hướng: {trend_icon} {technical.trend}\n"
            f"EMA20: {number(technical.ema20)}\n"
            f"EMA50: {number(technical.ema50)}\n"
            f"MA200: {number(technical.ma200)}\n"
            f"RSI14: {number(technical.rsi14)}\n"
            f"ADX14: {number(technical.adx14)}\n"
            f"ATR14: {number(technical.atr14)}\n"
            f"KL/TB20: {_ratio(technical.volume_ratio)}\n"
            f"RS vs VNINDEX (20 phiên): {percent(technical.relative_strength)}"
        ),
    ]
    levels = _levels_block(technical, verbose=True)
    if levels:
        blocks.append(levels)
    if technical.missing:
        blocks.append("Thiếu dữ liệu:\n" + "\n".join(f"? {item}" for item in technical.missing))
    blocks.append(_data_quality_block(view))
    blocks.append(f"{DIVIDER}\n⚠️ {DISCLAIMER}")
    return "\n\n".join(blocks)


def format_why(view: StockAnalysisView, interpretations: Sequence[str]) -> str:
    """Explainability: state → evidence → interpretation → next triggers."""
    if view.error:
        return view.error
    blocks: list[str] = [f"❓ {view.symbol} — VÌ SAO Ở TRẠNG THÁI NÀY?\n{HEADER_DIVIDER}"]
    if view.strategy is not None:
        strategy = view.strategy
        header = f"Chiến lược {strategy.name}: {strategy.state}"
        if strategy.evidence_total:
            header += f"\nĐộ phủ bằng chứng: {strategy.evidence_covered}/{strategy.evidence_total}"
            header += "\n(không phải xác suất đã hiệu chuẩn)"
        blocks.append(header)
        if strategy.positive:
            blocks.append("Tích cực:\n" + "\n".join(f"✓ {item}" for item in strategy.positive))
        if strategy.negative:
            blocks.append("Chưa đạt:\n" + "\n".join(f"⚠ {item}" for item in strategy.negative))
        if strategy.missing:
            blocks.append("Thiếu dữ liệu:\n" + "\n".join(f"? {item}" for item in strategy.missing))
        if strategy.layers:
            blocks.append(
                "Các tầng:\n" + "\n".join(
                    f"{item.name}: {item.status.value}"
                    + (f" — {item.detail}" if item.detail else "")
                    for item in strategy.layers
                )
            )
    if interpretations:
        blocks.append("Diễn giải chỉ báo:\n" + "\n".join(f"• {item}" for item in interpretations))
    if view.watch_items:
        blocks.append("Điều kiện cần theo dõi:\n" + "\n".join(f"→ {item}" for item in view.watch_items))
    if view.market is not None:
        blocks.append(
            "Bối cảnh thị trường:\n"
            f"{view.market.symbol} {number(view.market.close)} — {view.market.trend}; "
            f"regime {view.market.regime} ({view.market.regime_reason})"
        )
    if view.sentiment is not None:
        blocks.append("Bối cảnh tin tức:\n" + _sentiment_line(view.sentiment))
    limitations = list(view.data_quality.notes)
    if view.technical is not None:
        limitations.extend(view.technical.missing)
    if limitations:
        blocks.append("Giới hạn dữ liệu:\n" + "\n".join(f"- {item}" for item in dict.fromkeys(limitations)))
    blocks.append(format_data_quality(view.data_quality, include_notes=False))
    blocks.append(f"{DIVIDER}\n⚠️ Đây là context lịch sử; không phải khuyến nghị mua/bán.")
    return "\n\n".join(blocks)


def format_market(
    view: MarketContextView | None,
    sentiment: SentimentView | None,
    data_quality_text: str,
) -> str:
    if view is None:
        return "Chưa có dữ liệu lịch sử VNINDEX."

    trend_icon = "📈" if "TĂNG" in view.trend else "📉" if "GIẢM" in view.trend else "➡️"
    index_label = f"VN-Index ({view.symbol})" if view.symbol == "VNINDEX" else view.symbol
    header_block = (
        f"🌐 BỐI CẢNH THỊ TRƯỜNG\n"
        f"{HEADER_DIVIDER}\n"
        f"• {index_label}: {number(view.close)} ({percent(view.change_percent)})\n"
        f"• Xu hướng: {trend_icon} {view.trend}\n"
        f"• EMA20: {number(view.ema20)} | EMA50: {number(view.ema50)}"
    )

    blocks = [header_block]

    quant_lines = []
    if view.hurst is not None:
        if view.hurst > 0.55:
            cmp_str = "> 0.55"
            interp = f"Hurst = {view.hurst:.2f} > 0.55 -> thị trường có quán tính xu hướng."
        elif view.hurst < 0.45:
            cmp_str = "< 0.45"
            interp = f"Hurst = {view.hurst:.2f} < 0.45 -> thị trường có tính hồi quy trung bình (mean-reverting)."
        else:
            cmp_str = "0.45 - 0.55"
            interp = f"Hurst = {view.hurst:.2f} ≈ 0.50 -> thị trường dao động ngẫu nhiên (random walk)."

        vol_pct_str = (
            f"{int(round(view.volatility_percentile))}%"
            if view.volatility_percentile is not None
            else "N/A"
        )
        quant_lines.append(
            f"• Số mũ Hurst = {view.hurst:.2f} ({cmp_str}) - Phân vị biến động = {vol_pct_str}\n"
            f"(Dựa trên {view.hurst_lookback} phiên gần nhất)\n"
            f"• {interp}"
        )
    if view.trend_stability_reason:
        quant_lines.append(f"• {view.trend_stability_reason}")

    if quant_lines:
        blocks.append("\n".join(quant_lines))

    if view.top_sectors:
        sector_lines = ["🏭 Ngành mạnh nhất"]
        medals = ("🥇", "🥈", "🥉")
        for idx, sec in enumerate(view.top_sectors[:3]):
            medal = medals[idx] if idx < len(medals) else "•"
            sector_lines.append(f"{medal} {sec}")
        if view.weakest_sector:
            score_str = (
                f"{int(round(view.weakest_sector_score))}/100"
                if view.weakest_sector_score is not None
                else "N/A"
            )
            sector_lines.append(f"\nYếu nhất: {view.weakest_sector} — {score_str}")
        blocks.append("\n".join(sector_lines))

    blocks.extend(
        [
            f"REGIME: {view.regime}\nCơ sở: {view.regime_reason}",
            f"BREADTH: {view.breadth or 'unavailable'}",
            f"LIQUIDITY: {view.liquidity or 'unavailable'}",
            f"DÒNG TIỀN NGOẠI/TỰ DOANH: {view.foreign_flow or 'unavailable'}",
        ]
    )

    if sentiment is not None:
        blocks.append("📰 NEWS SENTIMENT\n" + _sentiment_line(sentiment))
    if view.risk_flags:
        blocks.append("⚠️ RISK FLAGS\n" + "\n".join(f"• {item}" for item in view.risk_flags))
    if view.unavailable:
        blocks.append("Chưa khả dụng:\n" + "\n".join(f"- {item}" for item in view.unavailable))
    blocks.append(data_quality_text)

    blocks.append(
        f"{DIVIDER}\n"
        "👉 Chọn một mục bên dưới để xem chi tiết:\n\n"
        "🔎 Chatbot này chỉ dùng với mục đích tham khảo."
    )
    return "\n\n".join(blocks)


def format_fundamental(view: StockAnalysisView) -> str:
    if view.error:
        return view.error
    if view.fundamental is None:
        return f"🧾 {view.symbol} — CƠ BẢN\nFundamental data missing."
    return "\n\n".join(
        [
            f"🧾 {view.symbol} — CƠ BẢN\n{HEADER_DIVIDER}",
            _fundamental_block(view.fundamental),
            _data_quality_block(view),
            f"{DIVIDER}\n⚠️ {DISCLAIMER}",
        ]
    )


SENTIMENT_TARGET_ARTICLE_COUNT = 5
SENTIMENT_WINDOW_DAYS = 30


def _sentiment_bucket(score: float, *, low_confidence: bool = False) -> str:
    if score <= -0.5:
        return "🟡 TIÊU CỰC (độ tin cậy thấp)" if low_confidence else "🔴 TIÊU CỰC"
    if score <= -0.15:
        return "🟡 TRUNG LẬP, HƠI NGHIÊNG TIÊU CỰC"
    if score < 0.15:
        return "🟡 TRUNG LẬP"
    if score < 0.5:
        return "🟡 TRUNG LẬP, HƠI NGHIÊNG TÍCH CỰC"
    return "🟡 TÍCH CỰC (độ tin cậy thấp)" if low_confidence else "🟢 TÍCH CỰC"


def _confidence_bucket(confidence: float | None) -> str:
    if confidence is None:
        return UNAVAILABLE
    if confidence >= 0.7:
        return "CAO"
    if confidence >= 0.4:
        return "TRUNG BÌNH"
    return "THẤP"


def format_sentiment(symbol: str, view: SentimentView | None) -> str:
    if view is None or not view.available:
        note = (view.note if view is not None and view.note else "News sentiment unavailable.")
        return f"🧠 {symbol} — SENTIMENT\n{note}"

    article_count = view.article_count or 0
    confidence_bucket = _confidence_bucket(view.model_confidence)
    low_coverage = article_count < SENTIMENT_TARGET_ARTICLE_COUNT or confidence_bucket == "THẤP"
    lines = [
        f"🧠 {symbol} — SENTIMENT\n{HEADER_DIVIDER}",
        "",
        _sentiment_bucket(view.score, low_confidence=low_coverage),
        f"Score: {view.score:+.2f}",
        f"Độ tin cậy: {confidence_bucket}",
    ]

    lines.append("")
    lines.append("📊 CẤU TRÚC TIN")
    lines.append(f"Tích cực: {view.positive_count if view.positive_count is not None else 0}")
    lines.append(f"Trung lập: {view.neutral_count if view.neutral_count is not None else 0}")
    lines.append(f"Tiêu cực: {view.negative_count if view.negative_count is not None else 0}")

    if view.top_events:
        lines.append("")
        lines.append("🧭 CHỦ ĐỀ")
        for event in view.top_events:
            lines.append(f"• {_event_label(event)}")

    if article_count < SENTIMENT_TARGET_ARTICLE_COUNT:
        lines.append("")
        lines.append(
            f"⚠️ Chỉ tìm được {article_count}/{SENTIMENT_TARGET_ARTICLE_COUNT} tin "
            f"trong {SENTIMENT_WINDOW_DAYS} ngày"
        )
        lines.append("→ độ phủ dữ liệu thấp.")

    lines.append("")
    lines.append("💡 ĐÁNH GIÁ")
    if low_coverage:
        lines.append("Sentiment hiện chưa đủ mạnh để tự tạo tín hiệu giao dịch.")
    else:
        lines.append("Sentiment là yếu tố tham khảo, không tự tạo tín hiệu giao dịch.")

    lines.append("")
    lines.append(f"📰 /tin {symbol} để xem bài gốc.")
    return "\n".join(lines)


EVENT_LABEL_MAP = {
    "LEGAL": "PHÁP LÝ",
    "EARNINGS": "KQKD",
    "MA": "M&A",
    "CAPITAL": "TĂNG VỐN",
    "MACRO": "VĨ MÔ",
    "DIVIDEND": "CỔ TỨC",
    "CONTRACT": "HỢP ĐỒNG",
    "MANAGEMENT": "NHÂN SỰ",
    "OTHER": "KHÁC",
}

SOURCE_LABEL_MAP = {
    "cafef_rss": "CafeF",
    "cafef_ticker": "CafeF",
}

SENTIMENT_LABEL_MAP_SHORT = {
    "POSITIVE": "Tích cực",
    "positive": "Tích cực",
    "NEGATIVE": "Tiêu cực",
    "negative": "Tiêu cực",
    "NEUTRAL": "Trung lập",
    "neutral": "Trung lập",
}


def _event_label(event_type: str) -> str:
    return EVENT_LABEL_MAP.get(event_type, event_type)


def _source_label(source: str) -> str:
    return SOURCE_LABEL_MAP.get(source, source)


def format_news(symbol: str, items: Sequence[NewsItemView]) -> str:
    if not items:
        return f"Không có tin gần đây cho {symbol}."
    lines = [f"📰 TIN MỚI NHẤT — {symbol}\n{HEADER_DIVIDER}"]
    for index, item in enumerate(items, start=1):
        sentiment_vn = SENTIMENT_LABEL_MAP_SHORT.get(item.sentiment_label or "", "Chưa có")
        entry = [
            f"{index}. {_time(item.published_at)} | {_event_label(item.event_type)}",
            f"   {item.title}",
            f"   Nguồn: {_source_label(item.source)} | Sentiment: {sentiment_vn}",
        ]
        if item.url:
            entry.append(f"   🔗 Đọc bài: {item.url}")
        lines.append("\n".join(entry))
    return "\n\n".join(lines)


def format_sector(view: SectorView | None) -> str:
    if view is None or view.sector_code is None:
        return "📁 NGÀNH\nKhông có dữ liệu ngành cho mã/ngành này."
    lines = [
        f"📁 NGÀNH {view.sector_code} — {view.sector_name or UNAVAILABLE}\n{HEADER_DIVIDER}",
        f"• Số mã trong ngành: {view.member_count if view.member_count is not None else UNAVAILABLE}",
        f"• Điểm sức mạnh ngành: {number(view.strength_score, 1)}/100",
        f"• Breadth (trên MA50): {number(view.breadth_percent, 1)}%",
        f"• RS ngành vs VNINDEX: {percent(view.relative_strength)}",
    ]
    if view.leaders:
        lines.append(f"{DIVIDER}\n🥇 Dẫn dắt: " + ", ".join(f"{s} {v:+.1f}%" for s, v in view.leaders))
    if view.laggards:
        lines.append("🥀 Yếu: " + ", ".join(f"{s} {v:+.1f}%" for s, v in view.laggards))
    if view.missing:
        lines.append(f"{DIVIDER}\nThiếu dữ liệu: " + "; ".join(view.missing))
    lines.append(DIVIDER)
    lines.append(f"📅 Ngày tham chiếu: {view.as_of or UNAVAILABLE} | Nguồn: {view.source or UNAVAILABLE}")
    return "\n".join(lines)


def format_scan(
    rows: Sequence[ScanRowView],
    *,
    as_of: str | None = None,
    scanned_at: int | None = None,
    total_universe: int | None = None,
    strategy: str = "CL1",
    stale: bool = False,
) -> str:
    if not rows:
        return "Chưa có mã đạt bộ lọc."
    header = f"🔎 KẾT QUẢ QUÉT — CHIẾN LƯỢC {strategy}" if strategy != "CL1" else "🔎 KẾT QUẢ QUÉT"
    lines = [f"{header}\n{HEADER_DIVIDER}"]
    if total_universe is not None or as_of is not None:
        info = []
        if total_universe is not None:
            info.append(f"Toàn thị trường: {len(rows)}/{total_universe} mã đạt lọc")
        if as_of is not None:
            info.append(f"Ngày: {as_of}")
        lines.append("📊 " + " | ".join(info))
        lines.append(DIVIDER)
    if stale:
        lines.append("⚠️ Dữ liệu quét đã cũ (worker chưa cập nhật gần đây) — kết quả có thể không còn mới.")
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row.symbol}\n"
            f"   • Xu hướng:   {row.trend}\n"
            f"   • RS:         {row.relative_strength}\n"
            f"   • Thanh khoản: {row.liquidity}\n"
            f"   • Cơ bản:     {row.fundamental}\n"
            f"   • Chiến lược: {row.strategy_state}"
        )
    lines.append(DIVIDER)
    lines.append("⚠️ Lọc theo thanh khoản + kỹ thuật; không phải danh sách khuyến nghị mua.")
    return "\n".join(lines)


def _levels_block(technical: TechnicalView, *, verbose: bool = False) -> str:
    if not technical.resistances and not technical.supports:
        return ""
    lines = ["📐 HỖ TRỢ / KHÁNG CỰ"]
    for level in technical.resistances:
        lines.append(
            f"🔴 {level.label}: {number(level.value)}" + (f" — {level.reason}" if verbose else "")
        )
    for level in technical.supports:
        lines.append(
            f"🟢 {level.label}: {number(level.value)}" + (f" — {level.reason}" if verbose else "")
        )
    return "\n".join(lines)


def _market_summary(market: MarketContextView) -> str:
    trend_icon = "📈" if "TĂNG" in market.trend else "📉" if "GIẢM" in market.trend else "➡️"
    return (
        "🌐 THỊ TRƯỜNG\n"
        f"• {market.symbol}: {number(market.close)} ({percent(market.change_percent)}) — {trend_icon} {market.trend}\n"
        f"• Regime: {market.regime} ({market.regime_reason})\n"
        f"• Breadth: {market.breadth or 'unavailable'}"
    )


def _strategy_block(strategy) -> str:
    lines = [f"🎯 Chiến lược {strategy.name}: {strategy.state}"]
    if strategy.score is not None:
        lines.append(f"• Điểm bằng chứng (Evidence score): {strategy.score:.1f}/100 (tổng hợp điểm, không phải xác suất)")
    if strategy.evidence_total:
        lines.append(f"• Độ phủ bằng chứng: {strategy.evidence_covered}/{strategy.evidence_total}")
    if strategy.layers:
        def _layer_label(item):
            name = "ASMF Market Filter" if strategy.name == "ASMF" and item.name == "Market" else item.name
            return f"{name}={item.status.value}"
        if strategy.name == "ASMF":
            core_layers = [i for i in strategy.layers if i.name != "Sentiment"]
            sentiment_layers = [i for i in strategy.layers if i.name == "Sentiment"]
            core_covered = sum(1 for i in core_layers if i.status.value != "MISSING")
            lines.append(f"• Độ phủ tầng cốt lõi: {core_covered}/{len(core_layers)} tầng")
            lines.append("• Tầng: " + " | ".join(_layer_label(i) for i in strategy.layers))
            if sentiment_layers:
                s = sentiment_layers[0]
                lines.append(f"• Lớp bổ trợ (Sentiment context): {s.status.value}" + (f" ({s.detail})" if s.detail else ""))
        else:
            lines.append("• Tầng: " + " | ".join(_layer_label(i) for i in strategy.layers))
    if strategy.positive:
        lines.append("• Đạt: " + "; ".join(strategy.positive))
    if strategy.negative:
        lines.append("• Chưa đạt: " + "; ".join(strategy.negative))
    if strategy.missing:
        lines.append("• Thiếu dữ liệu: " + "; ".join(strategy.missing))
    if strategy.stop is not None:
        lines.append(f"• Chandelier Exit: {strategy.stop:g}")
    if strategy.note:
        lines.append(f"• {strategy.note}")
    return "\n".join(lines)


def _fundamental_block(fundamental, *, compact: bool = False) -> str:
    lines = [f"🧾 CƠ BẢN: {fundamental.status}"]
    shown = [item for item in fundamental.metrics if item.value is not None]
    if compact:
        shown = shown[:4]
    for metric in shown:
        lines.append(f"• {metric.label}: {metric.value:,.2f}{metric.unit}")
    if not shown:
        lines.append("Fundamental data missing.")
    if fundamental.missing and not compact:
        lines.append("• Thiếu: " + ", ".join(fundamental.missing))
    if fundamental.period or fundamental.as_of:
        lines.append(
            f"• Kỳ báo cáo: {fundamental.period or UNAVAILABLE} | "
            f"As-of: {fundamental.as_of or UNAVAILABLE}"
        )
    if fundamental.source and not compact:
        lines.append(f"• Nguồn: {fundamental.source}")
    if fundamental.note and not compact:
        lines.append(f"• {fundamental.note}")
    return "\n".join(lines)


def _sentiment_block(sentiment: SentimentView, *, compact: bool = False) -> str:
    if not sentiment.available:
        header = "📰 SENTIMENT" if compact else "📰 SENTIMENT (5 TIN MỚI NHẤT)"
        return f"{header}\n" + (sentiment.note or "News sentiment unavailable.")
    if compact:
        latest = _time(sentiment.latest_at)
        return (
            "📰 SENTIMENT\n"
            f"{sentiment.label} | score {sentiment.score:+.2f} | {sentiment.article_count} bài\n"
            f"Tin mới nhất: {latest}"
        )
    return "📰 SENTIMENT (5 TIN MỚI NHẤT)\n" + _sentiment_line(sentiment)


def _sentiment_line(sentiment: SentimentView) -> str:
    if not sentiment.available:
        return sentiment.note or "News sentiment unavailable."
    return (
        f"{sentiment.label} | score {sentiment.score:+.2f} | "
        f"model confidence {number(sentiment.model_confidence)} | "
        f"{sentiment.article_count} bài\n"
        f"P/N/N: {sentiment.positive_count}/{sentiment.neutral_count}/{sentiment.negative_count} | "
        f"sự kiện: {', '.join(sentiment.top_events) or UNAVAILABLE}"
    )


def _data_quality_block(view: StockAnalysisView) -> str:
    return format_data_quality(view.data_quality)


def format_data_quality(quality, *, include_notes: bool = True) -> str:
    lines = ["🕒 DỮ LIỆU"]
    label = FRESHNESS_LABELS.get(quality.freshness, quality.freshness.value)
    if quality.staleness_days:
        label += f", cách {quality.staleness_days} ngày"
    lines.append(f"• Market data: {label}")
    lines.append(f"• Phiên dữ liệu: {quality.session_date or UNAVAILABLE}")
    lines.append(f"• Nguồn: {quality.market_source}")
    if quality.fundamental_source:
        lines.append(
            f"• Nguồn BCTC: {quality.fundamental_source} (as-of {quality.fundamental_as_of or UNAVAILABLE})"
        )
    if quality.news_source:
        lines.append(f"• Nguồn tin: {quality.news_source} (mới nhất {_time(quality.news_latest_at)})")
    if include_notes:
        for note in quality.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _ratio(value: float | None) -> str:
    return UNAVAILABLE if value is None else f"{value:.2f}x"


def _time(value) -> str:
    if value is None:
        return UNAVAILABLE
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        try:
            return value.astimezone(VIETNAM_TIMEZONE).strftime("%d/%m %H:%M")
        except Exception:
            pass
    return value.strftime("%d/%m %H:%M")

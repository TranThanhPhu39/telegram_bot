"""Telegram rendering for analysis views.

The formatter performs no computation and no data access.  It only renders what
a view already established, and it never crashes on ``None``: an unavailable
value is printed as an explicit unavailable marker.
"""

from __future__ import annotations

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

UNAVAILABLE = "N/A"
DISCLAIMER = "Tín hiệu định lượng, không phải khuyến nghị đầu tư."

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


def format_stock_overview(view: StockAnalysisView) -> str:
    """Compact dashboard; drill-down lives in /technical, /fundamental, /why."""
    if view.error:
        return view.error
    blocks: list[str] = [f"📊 {view.symbol} — TỔNG QUAN"]

    if view.price is not None:
        blocks.append(
            "💰 GIÁ\n"
            f"Đóng cửa: {number(view.price.close)} ({percent(view.price.change_percent)})\n"
            f"Khối lượng: {integer(view.price.volume)}\n"
            f"Dữ liệu phiên: {view.price.session_date or UNAVAILABLE}"
        )

    if view.technical is not None:
        technical = view.technical
        blocks.append(
            "📈 KỸ THUẬT\n"
            f"Xu hướng: {technical.trend}\n"
            f"EMA20: {number(technical.ema20)} | EMA50: {number(technical.ema50)}\n"
            f"RSI14: {number(technical.rsi14)} | ADX14: {number(technical.adx14)}\n"
            f"KL/TB20: {_ratio(technical.volume_ratio)} | "
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

    blocks.append(_data_quality_block(view))
    blocks.append("Gõ /why " + view.symbol + " để xem giải thích chi tiết.")
    blocks.append(DISCLAIMER)
    return "\n\n".join(blocks)


def format_technical(view: StockAnalysisView) -> str:
    if view.error:
        return view.error
    if view.technical is None:
        return f"Chưa đủ dữ liệu kỹ thuật cho {view.symbol}."
    technical = view.technical
    blocks = [
        f"📈 {view.symbol} — KỸ THUẬT",
        (
            f"Xu hướng: {technical.trend}\n"
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
    blocks.append(DISCLAIMER)
    return "\n\n".join(blocks)


def format_why(view: StockAnalysisView, interpretations: Sequence[str]) -> str:
    """Explainability: state → evidence → interpretation → next triggers."""
    if view.error:
        return view.error
    blocks: list[str] = [f"❓ {view.symbol} — VÌ SAO Ở TRẠNG THÁI NÀY?"]
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
    blocks.append(_data_quality_block(view))
    blocks.append("Đây là context lịch sử; không phải khuyến nghị mua/bán.")
    return "\n\n".join(blocks)


def format_market(
    view: MarketContextView | None,
    sentiment: SentimentView | None,
    data_quality_text: str,
) -> str:
    if view is None:
        return "Chưa có dữ liệu lịch sử VNINDEX."
    blocks = [
        "🌐 THỊ TRƯỜNG",
        (
            f"{view.symbol}\n"
            f"Điểm số: {number(view.close)} ({percent(view.change_percent)})\n"
            f"Xu hướng: {view.trend}\n"
            f"EMA20: {number(view.ema20)} | EMA50: {number(view.ema50)}"
        ),
        f"REGIME: {view.regime}\nCơ sở: {view.regime_reason}",
        f"BREADTH: {view.breadth or 'unavailable'}",
        f"LIQUIDITY: {view.liquidity or 'unavailable'}",
        f"DÒNG TIỀN NGOẠI/TỰ DOANH: {view.foreign_flow or 'unavailable'}",
    ]
    if sentiment is not None:
        blocks.append("📰 NEWS SENTIMENT\n" + _sentiment_line(sentiment))
    if view.risk_flags:
        blocks.append("⚠️ RISK FLAGS\n" + "\n".join(f"• {item}" for item in view.risk_flags))
    if view.unavailable:
        blocks.append("Chưa khả dụng:\n" + "\n".join(f"- {item}" for item in view.unavailable))
    blocks.append(data_quality_text)
    return "\n\n".join(blocks)


def format_fundamental(view: StockAnalysisView) -> str:
    if view.error:
        return view.error
    if view.fundamental is None:
        return f"🧾 {view.symbol} — CƠ BẢN\nFundamental data missing."
    return "\n\n".join(
        [f"🧾 {view.symbol} — CƠ BẢN", _fundamental_block(view.fundamental), _data_quality_block(view)]
    )


def format_sentiment(symbol: str, view: SentimentView | None) -> str:
    if view is None or not view.available:
        note = (view.note if view is not None and view.note else "News sentiment unavailable.")
        return f"📰 {symbol} — SENTIMENT 24H\n{note}"
    lines = [
        f"📰 {symbol} — SENTIMENT 24H",
        f"Nhãn tổng hợp: {view.label}",
        f"Score: {view.score:+.2f} (thang -1..+1, có giảm trọng số theo thời gian)",
        f"Model confidence: {number(view.model_confidence)} (độ tin cậy của bộ phân loại, "
        "không phải xác suất giá tăng)",
        f"Số bài: {view.article_count}",
        f"Positive/Neutral/Negative: {view.positive_count}/{view.neutral_count}/{view.negative_count}",
        f"Sự kiện chính: {', '.join(view.top_events) or UNAVAILABLE}",
        f"Tin mới nhất: {_time(view.latest_at)}",
        f"Model backend: {', '.join(view.backends) or UNAVAILABLE}",
        "",
        "Sentiment là context; tự nó không tạo tín hiệu MUA.",
    ]
    return "\n".join(lines)


def format_news(symbol: str, items: Sequence[NewsItemView]) -> str:
    if not items:
        return f"Không có tin gần đây cho {symbol}."
    lines = [f"📰 TIN MỚI NHẤT — {symbol}"]
    for item in items:
        lines.append(
            f"• {item.published_at:%d/%m %H:%M} | {item.event_type} | "
            f"{item.sentiment_label or 'unavailable'} | {item.source}\n{item.title}"
        )
    return "\n".join(lines)


def format_sector(view: SectorView | None) -> str:
    if view is None or view.sector_code is None:
        return "📁 NGÀNH\nKhông có dữ liệu ngành cho mã/ngành này."
    lines = [
        f"📁 NGÀNH {view.sector_code} — {view.sector_name or UNAVAILABLE}",
        f"Số mã trong ngành: {view.member_count if view.member_count is not None else UNAVAILABLE}",
        f"Điểm sức mạnh ngành: {number(view.strength_score, 1)}/100",
        f"Breadth (trên MA50): {number(view.breadth_percent, 1)}%",
        f"RS ngành vs VNINDEX: {percent(view.relative_strength)}",
    ]
    if view.leaders:
        lines.append("Dẫn dắt: " + ", ".join(f"{s} {v:+.1f}%" for s, v in view.leaders))
    if view.laggards:
        lines.append("Yếu: " + ", ".join(f"{s} {v:+.1f}%" for s, v in view.laggards))
    if view.missing:
        lines.append("Thiếu dữ liệu: " + "; ".join(view.missing))
    lines.append(f"Ngày tham chiếu: {view.as_of or UNAVAILABLE} | Nguồn: {view.source or UNAVAILABLE}")
    return "\n".join(lines)


def format_scan(rows: Sequence[ScanRowView]) -> str:
    if not rows:
        return "Chưa có mã đạt bộ lọc."
    lines = ["🔎 KẾT QUẢ QUÉT"]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {row.symbol}\n"
            f"   Xu hướng: {row.trend}\n"
            f"   RS: {row.relative_strength}\n"
            f"   Thanh khoản: {row.liquidity}\n"
            f"   Cơ bản: {row.fundamental}\n"
            f"   Chiến lược: {row.strategy_state}"
        )
    lines.append("Lọc theo thanh khoản + kỹ thuật; không phải danh sách khuyến nghị mua.")
    return "\n".join(lines)


def _levels_block(technical: TechnicalView, *, verbose: bool = False) -> str:
    if not technical.resistances and not technical.supports:
        return ""
    lines = ["📐 HỖ TRỢ / KHÁNG CỰ"]
    for level in technical.resistances:
        lines.append(
            f"{level.label}: {number(level.value)}" + (f" — {level.reason}" if verbose else "")
        )
    for level in technical.supports:
        lines.append(
            f"{level.label}: {number(level.value)}" + (f" — {level.reason}" if verbose else "")
        )
    return "\n".join(lines)


def _market_summary(market: MarketContextView) -> str:
    return (
        "🌐 THỊ TRƯỜNG\n"
        f"{market.symbol}: {number(market.close)} ({percent(market.change_percent)}) — {market.trend}\n"
        f"Regime: {market.regime} ({market.regime_reason})\n"
        f"Breadth: {market.breadth or 'unavailable'}"
    )


def _strategy_block(strategy) -> str:
    lines = [f"🎯 Chiến lược {strategy.name}: {strategy.state}"]
    if strategy.score is not None:
        lines.append(f"Điểm hiện có: {strategy.score:.1f}/100 (chưa hiệu chuẩn lịch sử)")
    if strategy.evidence_total:
        lines.append(f"Độ phủ bằng chứng: {strategy.evidence_covered}/{strategy.evidence_total}")
    if strategy.layers:
        lines.append("Tầng: " + " | ".join(f"{i.name}={i.status.value}" for i in strategy.layers))
    if strategy.positive:
        lines.append("Đạt: " + "; ".join(strategy.positive))
    if strategy.negative:
        lines.append("Chưa đạt: " + "; ".join(strategy.negative))
    if strategy.missing:
        lines.append("Thiếu dữ liệu: " + "; ".join(strategy.missing))
    if strategy.stop is not None:
        lines.append(f"Chandelier Exit: {strategy.stop:g}")
    if strategy.note:
        lines.append(strategy.note)
    return "\n".join(lines)


def _fundamental_block(fundamental, *, compact: bool = False) -> str:
    lines = [f"🧾 CƠ BẢN: {fundamental.status}"]
    shown = [item for item in fundamental.metrics if item.value is not None]
    if compact:
        shown = shown[:4]
    for metric in shown:
        lines.append(f"{metric.label}: {metric.value:,.2f}{metric.unit}")
    if not shown:
        lines.append("Fundamental data missing.")
    if fundamental.missing and not compact:
        lines.append("Thiếu: " + ", ".join(fundamental.missing))
    if fundamental.period or fundamental.as_of:
        lines.append(
            f"Kỳ báo cáo: {fundamental.period or UNAVAILABLE} | "
            f"As-of: {fundamental.as_of or UNAVAILABLE}"
        )
    if fundamental.source and not compact:
        lines.append(f"Nguồn: {fundamental.source}")
    if fundamental.note and not compact:
        lines.append(fundamental.note)
    return "\n".join(lines)


def _sentiment_block(sentiment: SentimentView, *, compact: bool = False) -> str:
    return "📰 TIN 24H\n" + _sentiment_line(sentiment)


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


def format_data_quality(quality) -> str:
    lines = ["🕒 DỮ LIỆU"]
    label = FRESHNESS_LABELS.get(quality.freshness, quality.freshness.value)
    if quality.staleness_days:
        label += f", cách {quality.staleness_days} ngày"
    lines.append(f"Market data: {label}")
    lines.append(f"Phiên dữ liệu: {quality.session_date or UNAVAILABLE}")
    lines.append(f"Nguồn: {quality.market_source}")
    if quality.fundamental_source:
        lines.append(
            f"Nguồn BCTC: {quality.fundamental_source} (as-of {quality.fundamental_as_of or UNAVAILABLE})"
        )
    if quality.news_source:
        lines.append(f"Nguồn tin: {quality.news_source} (mới nhất {_time(quality.news_latest_at)})")
    for note in quality.notes:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _ratio(value: float | None) -> str:
    return UNAVAILABLE if value is None else f"{value:.2f}x"


def _time(value) -> str:
    return UNAVAILABLE if value is None else value.strftime("%d/%m %H:%M")

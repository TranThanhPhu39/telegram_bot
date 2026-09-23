"""Unit tests for the redesigned format_scan output (F1 scanner UX pass).

Covers: shorter per-row output, grouping by trend, the renamed SELL state,
the scan timestamp, and the Universe/Qua prescreen/Hiển thị coverage line.
"""

from __future__ import annotations

from runtime.analysis import STATE_LABELS
from runtime.views import ScanRowView
from strategy.technical_strategies import StrategyAction
from telegram_bot.formatters import format_scan


def _row(symbol: str, trend: str, strategy_state: str = "THEO DÕI") -> ScanRowView:
    return ScanRowView(
        symbol=symbol,
        trend=trend,
        relative_strength="+1.23% vs VNINDEX",
        liquidity="PASS",
        strategy_state=strategy_state,
        fundamental="PASS",
    )


def test_format_scan_groups_rows_by_trend() -> None:
    rows = [
        _row("VIC", "TĂNG"),
        _row("HPG", "GIẢM"),
        _row("VNM", "TRUNG TÍNH"),
    ]
    text = format_scan(rows, total_universe=1523, prescreen_count=42)

    up_idx = text.index("ƯU TIÊN")
    neutral_idx = text.index("TRUNG TÍNH / CHƯA RÕ")
    down_idx = text.index("YẾU")
    vic_idx = text.index("VIC")
    hpg_idx = text.index("HPG")
    vnm_idx = text.index("VNM")

    # Group headers appear in order, and each symbol appears after its header.
    assert up_idx < neutral_idx < down_idx
    assert up_idx < vic_idx < neutral_idx
    assert neutral_idx < vnm_idx < down_idx
    assert down_idx < hpg_idx


def test_format_scan_omits_empty_trend_groups() -> None:
    text = format_scan([_row("VIC", "TĂNG")], total_universe=10, prescreen_count=1)
    assert "ƯU TIÊN" in text
    assert "TRUNG TÍNH / CHƯA RÕ" not in text
    assert "YẾU" not in text


def test_format_scan_shows_coverage_funnel_not_ambiguous_ratio() -> None:
    """Issue 3.4: '20/1523 mã đạt lọc' looked like only 20 symbols passed."""
    text = format_scan([_row("VIC", "TĂNG")], total_universe=1523, prescreen_count=87)
    assert "mã đạt lọc" not in text
    assert "Vũ trụ: 1,523" in text
    assert "Qua prescreen: 87" in text
    assert "Hiển thị: Top 1" in text


def test_format_scan_shows_timestamp() -> None:
    # 2026-01-15 08:00:00 UTC -> 15:00 Vietnam time (UTC+7)
    text = format_scan([_row("VIC", "TĂNG")], scanned_at=1_768_464_000)
    assert "🕒" in text
    assert "15:00" in text


def test_format_scan_rows_are_single_line_and_do_not_repeat_liquidity() -> None:
    """Issue 3.5: no more 5-line-per-symbol blocks or a PASS repeated per row."""
    text = format_scan([_row("VIC", "TĂNG")], total_universe=10, prescreen_count=1)
    row_line = next(line for line in text.splitlines() if line.startswith("1. VIC"))
    assert "\n" not in row_line
    assert "Thanh khoản" not in row_line  # liquidity is implied, not repeated per row
    assert "RS" in row_line


def test_sell_state_label_is_not_an_order_to_sell() -> None:
    """Issue 3.6: a user who never held the symbol shouldn't read 'BÁN'."""
    label = STATE_LABELS[StrategyAction.SELL]
    assert label != "BÁN/THOÁT"
    assert not label.upper().startswith("BÁN")
    assert "GIỮ" in label or "TRÁNH" in label

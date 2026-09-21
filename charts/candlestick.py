"""Deterministic candlestick chart rendering from normalized OHLCV bars.

This module is intentionally provider- and strategy-independent: it consumes
only ``data.models.OHLCVBar`` and ``data.indicators.ema``, and returns raw PNG
bytes. It never calls Vietcap, SQLite, ASMF/CL1 strategy code, or Telegram.

Rendering uses only Pillow (already a pinned dependency for OCR) and its
built-in bitmap font, so output is reproducible across machines without a
system font dependency and without adding a new library such as matplotlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from data.indicators import ema
from data.models import OHLCVBar

MIN_BARS_FOR_CHART = 5
DEFAULT_VISIBLE_COUNT = 90
DEFAULT_EMA_PERIODS = (20, 50)

_BACKGROUND = (19, 23, 34)
_GRID = (42, 46, 57)
_TEXT = (200, 205, 215)
_UP = (38, 166, 91)
_DOWN = (217, 60, 60)
_WICK_UP = (63, 195, 122)
_WICK_DOWN = (235, 90, 90)
_VOLUME_UP = (38, 116, 91)
_VOLUME_DOWN = (140, 50, 50)
_EMA_COLORS = ((242, 195, 87), (108, 168, 255), (200, 120, 255))

_MARGIN_LEFT = 66
_MARGIN_RIGHT = 16
_MARGIN_TOP = 44
_MARGIN_BOTTOM = 28
_VOLUME_PANE_RATIO = 0.18
_PANE_GAP = 10


class ChartRenderError(ValueError):
    """Raised when the requested candlestick chart cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class CandlestickChart:
    """The rendered chart plus the metadata a Telegram caption can quote."""

    png_bytes: bytes
    symbol: str
    timeframe: str
    visible_bars: int
    first_timestamp: int
    last_timestamp: int
    last_close: float


def render_candlestick(
    bars: Sequence[OHLCVBar],
    *,
    visible_count: int = DEFAULT_VISIBLE_COUNT,
    width: int = 960,
    height: int = 540,
    ema_periods: tuple[int, ...] = DEFAULT_EMA_PERIODS,
    title: str | None = None,
) -> CandlestickChart:
    """Render a candlestick + volume PNG using up to ``visible_count`` bars.

    ``bars`` should be the caller's *full* available chronological history so
    EMA warm-up is computed correctly; only the most recent ``visible_count``
    bars are drawn. Raises :class:`ChartRenderError` for anything that would
    make the image misleading (too few bars, non-chronological input, mixed
    symbols/timeframes) rather than silently drawing a broken chart.
    """
    checked = _validate_bars(bars)
    if len(checked) < MIN_BARS_FOR_CHART:
        raise ChartRenderError(
            f"cần tối thiểu {MIN_BARS_FOR_CHART} phiên để vẽ biểu đồ nến, "
            f"hiện có {len(checked)}"
        )
    if visible_count < MIN_BARS_FOR_CHART:
        raise ChartRenderError("visible_count must be at least MIN_BARS_FOR_CHART")
    if width < 240 or height < 160:
        raise ChartRenderError("chart dimensions are too small to render")
    for period in ema_periods:
        if period < 1:
            raise ChartRenderError("ema_periods must be positive")

    ema_series = {period: ema(checked, period) for period in ema_periods}
    visible = _visible_bars(checked, visible_count)
    offset = len(checked) - len(visible)
    visible_emas = {
        period: tuple(series[offset:]) for period, series in ema_series.items()
    }

    image = Image.new("RGB", (width, height), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    volume_height = int((height - _MARGIN_TOP - _MARGIN_BOTTOM) * _VOLUME_PANE_RATIO)
    price_top = _MARGIN_TOP
    price_bottom = height - _MARGIN_BOTTOM - volume_height - _PANE_GAP
    volume_top = price_bottom + _PANE_GAP
    volume_bottom = height - _MARGIN_BOTTOM
    plot_left = _MARGIN_LEFT
    plot_right = width - _MARGIN_RIGHT

    price_min = min(bar.low for bar in visible)
    price_max = max(bar.high for bar in visible)
    for series in visible_emas.values():
        finite = [value for value in series if value is not None]
        if finite:
            price_min = min(price_min, min(finite))
            price_max = max(price_max, max(finite))
    if price_max <= price_min:
        price_max = price_min + max(price_min * 0.01, 1.0)
    price_pad = (price_max - price_min) * 0.06
    price_min -= price_pad
    price_max += price_pad

    max_volume = max((bar.volume for bar in visible), default=0.0)
    max_volume = max_volume if max_volume > 0 else 1.0

    slot_width = (plot_right - plot_left) / len(visible)
    body_width = max(1.0, slot_width * 0.6)

    def price_y(price: float) -> float:
        span = price_max - price_min
        ratio = (price - price_min) / span
        return price_bottom - ratio * (price_bottom - price_top)

    def volume_y(volume: float) -> float:
        ratio = volume / max_volume
        return volume_bottom - ratio * (volume_bottom - volume_top)

    _draw_price_grid(draw, font, plot_left, plot_right, price_top, price_bottom,
                      price_min, price_max)
    draw.rectangle(
        (plot_left, volume_top, plot_right, volume_bottom), outline=_GRID
    )

    for index, bar in enumerate(visible):
        center_x = plot_left + slot_width * (index + 0.5)
        up = bar.close >= bar.open
        candle_color = _UP if up else _DOWN
        wick_color = _WICK_UP if up else _WICK_DOWN

        draw.line(
            (center_x, price_y(bar.high), center_x, price_y(bar.low)),
            fill=wick_color, width=1,
        )
        top = price_y(max(bar.open, bar.close))
        bottom = price_y(min(bar.open, bar.close))
        if bottom - top < 1:
            bottom = top + 1
        draw.rectangle(
            (center_x - body_width / 2, top, center_x + body_width / 2, bottom),
            fill=candle_color,
        )

        volume_color = _VOLUME_UP if up else _VOLUME_DOWN
        draw.rectangle(
            (
                center_x - body_width / 2, volume_y(bar.volume),
                center_x + body_width / 2, volume_bottom,
            ),
            fill=volume_color,
        )

    for series_index, (period, series) in enumerate(sorted(visible_emas.items())):
        color = _EMA_COLORS[series_index % len(_EMA_COLORS)]
        points: list[tuple[float, float]] = []
        for index, value in enumerate(series):
            if value is None:
                if len(points) >= 2:
                    draw.line(points, fill=color, width=2)
                points = []
                continue
            center_x = plot_left + slot_width * (index + 0.5)
            points.append((center_x, price_y(value)))
        if len(points) >= 2:
            draw.line(points, fill=color, width=2)
        legend_x = plot_left + series_index * 90
        draw.line(
            (legend_x, _MARGIN_TOP - 16, legend_x + 18, _MARGIN_TOP - 16),
            fill=color, width=2,
        )
        draw.text(
            (legend_x + 24, _MARGIN_TOP - 22), f"EMA{period}",
            fill=_TEXT, font=font,
        )

    heading = title or f"{visible[0].symbol} {visible[0].timeframe}"
    draw.text((_MARGIN_LEFT, 8), heading, fill=_TEXT, font=font)
    last_close = visible[-1].close
    close_text = f"Close: {last_close:,.2f}"
    close_width = draw.textlength(close_text, font=font)
    draw.text(
        (plot_right - close_width, 8), close_text, fill=_TEXT, font=font
    )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return CandlestickChart(
        png_bytes=buffer.getvalue(),
        symbol=visible[0].symbol,
        timeframe=visible[0].timeframe,
        visible_bars=len(visible),
        first_timestamp=visible[0].timestamp,
        last_timestamp=visible[-1].timestamp,
        last_close=last_close,
    )


def _visible_bars(
    bars: tuple[OHLCVBar, ...], visible_count: int
) -> tuple[OHLCVBar, ...]:
    return bars[-visible_count:] if len(bars) > visible_count else bars


def _validate_bars(bars: Sequence[OHLCVBar]) -> tuple[OHLCVBar, ...]:
    checked = tuple(bars)
    if not checked:
        raise ChartRenderError("no bars supplied")
    symbol = checked[0].symbol
    timeframe = checked[0].timeframe
    previous_timestamp: int | None = None
    for bar in checked:
        if not isinstance(bar, OHLCVBar):
            raise ChartRenderError("bars must be OHLCVBar instances")
        if bar.symbol != symbol or bar.timeframe != timeframe:
            raise ChartRenderError("bars must share one symbol and timeframe")
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ChartRenderError("bars must be strictly chronological")
        previous_timestamp = bar.timestamp
    return checked


def _draw_price_grid(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    plot_left: float,
    plot_right: float,
    plot_top: float,
    plot_bottom: float,
    price_min: float,
    price_max: float,
    *,
    lines: int = 4,
) -> None:
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), outline=_GRID)
    for step in range(lines + 1):
        ratio = step / lines
        y = plot_bottom - ratio * (plot_bottom - plot_top)
        price = price_min + ratio * (price_max - price_min)
        draw.line((plot_left, y, plot_right, y), fill=_GRID, width=1)
        draw.text((4, y - 6), f"{price:,.1f}", fill=_TEXT, font=font)

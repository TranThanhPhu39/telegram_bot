"""Deterministic, provider-independent chart rendering.

Rendering consumes only ``data.models.OHLCVBar`` and ``data.indicators``
output. It never calls a provider, never touches strategy/ASMF decision
logic, and never depends on Telegram. Telegram code sends the resulting PNG
bytes as a photo; it does not draw pixels itself.
"""

from charts.candlestick import CandlestickChart, ChartRenderError, render_candlestick
from charts.sector_chart import SectorSeries, render_sector_performance_chart

__all__ = [
    "CandlestickChart",
    "ChartRenderError",
    "render_candlestick",
    "SectorSeries",
    "render_sector_performance_chart",
]

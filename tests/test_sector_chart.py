"""Tests for Top % Sector Performance Chart rendering."""

from __future__ import annotations

import pytest

from charts.sector_chart import (
    PNG_MAGIC,
    SectorSeries,
    render_sector_performance_chart,
)


def test_sector_performance_chart_renders_valid_png() -> None:
    dates = ("21/08", "26/08", "03/09", "08/09", "11/09", "16/09", "21/09")
    series = [
        SectorSeries(
            sector_code="OIL",
            sector_name="Dầu khí",
            cumulative_returns=(0.0, 1.2, 3.5, 4.8, 6.0, 6.5, 7.2),
            turnover_billion=1138.0,
            latest_return=7.2,
        ),
        SectorSeries(
            sector_code="REAL_ESTATE",
            sector_name="Bất động sản",
            cumulative_returns=(0.0, 2.5, 6.0, 10.2, 7.5, 6.8, 5.4),
            turnover_billion=2762.0,
            latest_return=5.4,
        ),
        SectorSeries(
            sector_code="BANK",
            sector_name="Ngân hàng",
            cumulative_returns=(0.0, 2.0, 2.1, 3.8, 1.5, 2.0, 2.63),
            turnover_billion=2856.0,
            latest_return=2.63,
        ),
        SectorSeries(
            sector_code="CHEM",
            sector_name="Hóa chất & Phân bón",
            cumulative_returns=(0.0, 1.0, 0.5, 2.5, 1.8, 2.0, 1.53),
            turnover_billion=244.0,
            latest_return=1.53,
        ),
        SectorSeries(
            sector_code="INSURANCE",
            sector_name="Bảo hiểm",
            cumulative_returns=(0.0, 0.5, -1.0, -0.8, -2.5, 0.5, 0.90),
            turnover_billion=47.0,
            latest_return=0.90,
        ),
    ]

    png_bytes = render_sector_performance_chart(series, dates, "21-09-2026 16:40")

    assert png_bytes.startswith(PNG_MAGIC)
    assert len(png_bytes) > 1000


def test_sector_chart_raises_on_empty_series() -> None:
    with pytest.raises(ValueError, match="ít nhất một ngành"):
        render_sector_performance_chart([], ("01/01", "02/01"), "02-01-2026 15:00")


def test_sector_chart_raises_on_insufficient_dates() -> None:
    series = [
        SectorSeries("BANK", "Ngân hàng", (1.0,), 100.0, 1.0),
    ]
    with pytest.raises(ValueError, match="tối thiểu 2 phiên"):
        render_sector_performance_chart(series, ("01/01",), "01-01-2026 15:00")


def test_sector_chart_raises_on_length_mismatch() -> None:
    series = [
        SectorSeries("BANK", "Ngân hàng", (1.0, 2.0), 100.0, 2.0),
    ]
    with pytest.raises(ValueError, match="không khớp số phiên"):
        render_sector_performance_chart(series, ("01/01", "02/01", "03/01"), "03-01-2026 15:00")

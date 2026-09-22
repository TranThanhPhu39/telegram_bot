"""Deterministic Top % Sector Performance Chart rendering.

Renders an equal-weight cumulative return comparison chart across
the leading market sectors over the last N sessions (default 20).
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from typing import Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Distinct, high-contrast palette matching modern financial charts
PALETTE = (
    "#2563EB",  # Blue (Dầu khí / Blue-chip)
    "#DC2626",  # Red (Bất động sản)
    "#059669",  # Green / Emerald (Ngân hàng)
    "#7C3AED",  # Purple (Hóa chất & Phân bón)
    "#D97706",  # Amber / Orange (Bảo hiểm)
    "#0891B2",  # Cyan
    "#DB2777",  # Pink
)


@dataclass(frozen=True, slots=True)
class SectorSeries:
    """Equal-weight cumulative performance series for one sector."""

    sector_code: str
    sector_name: str
    cumulative_returns: tuple[float, ...]  # Array of % returns relative to T0 (starts at 0.0)
    turnover_billion: float  # Latest session turnover in billion VND
    latest_return: float  # cumulative_returns[-1]


def render_sector_performance_chart(
    series: Sequence[SectorSeries],
    dates: Sequence[str],
    as_of_text: str,
) -> bytes:
    """Render Top % Sector Performance Chart into PNG bytes.

    Parameters:
        series: Sequence of SectorSeries to plot (typically top 5 sectors).
        dates: Sequence of date tick strings (e.g. ['21/08', '26/08', ..., '21/09']).
        as_of_text: Timestamp string displayed in the subtitle (e.g. '21-09-2026 16:40').

    Returns:
        Raw bytes of the rendered PNG image starting with PNG_MAGIC.
    """
    if not series:
        raise ValueError("Cần ít nhất một ngành để vẽ biểu đồ.")
    if len(dates) < 2:
        raise ValueError("Cần tối thiểu 2 phiên để vẽ biểu đồ ngành.")

    n_points = len(dates)
    for s in series:
        if len(s.cumulative_returns) != n_points:
            raise ValueError(
                f"Chuỗi dữ liệu ngành {s.sector_name} ({len(s.cumulative_returns)}) "
                f"không khớp số phiên ({n_points})."
            )

    fig, ax = plt.subplots(figsize=(8.0, 5.0), dpi=150)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    # Title & Subtitle matching the requirement
    fig.text(
        0.5,
        0.96,
        "TOP % BIẾN ĐỘNG NGÀNH",
        ha="center",
        va="top",
        fontsize=12,
        fontweight="bold",
        color="#111827",
    )
    fig.text(
        0.5,
        0.91,
        f"NGÀY: {as_of_text}",
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
        color="#374151",
    )

    ax.set_ylabel("BIẾN ĐỘNG LŨY KẾ (%)", fontsize=9, fontweight="bold", color="#374151")
    ax.set_xlabel(f"{n_points} phiên gần nhất", fontsize=9, color="#4b5563")

    # Dotted zero baseline
    ax.axhline(0, color="#9ca3af", linestyle="--", linewidth=1.0, alpha=0.85)

    # Grid
    ax.grid(True, linestyle=":", alpha=0.5, color="#d1d5db")

    x = list(range(n_points))

    # Plot sector lines
    for idx, item in enumerate(series):
        color = PALETTE[idx % len(PALETTE)]
        sign = "+" if item.latest_return >= 0 else ""
        turnover_str = f"{item.turnover_billion:,.0f} tỷ" if item.turnover_billion > 0 else "N/A"
        label = f"{item.sector_name} - {turnover_str} | {sign}{item.latest_return:.2f}%"
        ax.plot(
            x,
            item.cumulative_returns,
            label=label,
            color=color,
            linewidth=1.8,
            alpha=0.9,
        )

    # Date ticks on X axis
    tick_step = max(1, (n_points - 1) // 6)
    tick_indices = list(range(0, n_points, tick_step))
    if tick_indices[-1] != n_points - 1:
        tick_indices.append(n_points - 1)

    ax.set_xticks(tick_indices)
    ax.set_xticklabels([dates[i] for i in tick_indices], fontsize=8, color="#374151")
    ax.tick_params(axis="y", labelsize=8, colors="#374151")

    for spine in ax.spines.values():
        spine.set_color("#9ca3af")
        spine.set_linewidth(0.8)

    # Legend in top-left with border
    ax.legend(
        loc="upper left",
        frameon=True,
        facecolor="#ffffff",
        edgecolor="#d1d5db",
        framealpha=0.95,
        fontsize=7.5,
    )

    plt.subplots_adjust(top=0.86, bottom=0.12, left=0.10, right=0.95)

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    png_bytes = buffer.getvalue()
    if not png_bytes.startswith(PNG_MAGIC):
        raise RuntimeError("Generated chart data does not start with PNG magic bytes")
    return png_bytes

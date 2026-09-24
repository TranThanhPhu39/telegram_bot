"""Preliminary daily historical backtest using the shared SignalEngine.

This bounded diagnostic uses daily volume/average daily volume as a temporary
volume proxy because historical intraday sessions and historical breadth are not
available from the current Phase 8 boundary. Results are not production claims.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from backtest.engine import format_performance, run_backtest
from data.indicators import breakout_levels, daily_average_volume, ema20, ema50, relative_strength_vs_benchmark
from data.market_regime import MarketRegime
from data.vietcap.historical import normalize_gap_chart
from data.vietcap.rest import VietcapRestClient, VietcapTimeFrame
from strategy.signal_engine import SignalEngine, SignalEngineConfig, SignalInputs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    secrets = [os.getenv(name, "").strip() for name in ("VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE")]
    if not all(secrets):
        print("[NOT TESTED] Missing Vietcap session credentials")
        return 2
    client = VietcapRestClient(authorization=secrets[0], device_id=secrets[1], cookie=secrets[2])
    to_timestamp = int(os.getenv("BACKTEST_TO_TIMESTAMP", "1790035200"))
    stock_symbol = os.getenv("BACKTEST_SYMBOL", "ACB").strip().upper()
    stock_payload = client.get_gap_chart(
        (stock_symbol,), time_frame=VietcapTimeFrame.ONE_DAY,
        count_back=170, to_timestamp=to_timestamp,
    )
    benchmark_payload = client.get_gap_chart(
        ("VNINDEX",), time_frame=VietcapTimeFrame.ONE_DAY,
        count_back=170, to_timestamp=to_timestamp,
    )
    stock = tuple(
        bar for bar in normalize_gap_chart(stock_payload, time_frame=VietcapTimeFrame.ONE_DAY)
        if bar.symbol == stock_symbol
    )
    benchmark = tuple(
        bar for bar in normalize_gap_chart(benchmark_payload, time_frame=VietcapTimeFrame.ONE_DAY)
        if bar.symbol == "VNINDEX"
    )
    benchmark_by_time = {bar.timestamp: bar for bar in benchmark}
    raw_stock_count = len(stock)
    raw_benchmark_count = len(benchmark)
    stock = tuple(bar for bar in stock if bar.timestamp in benchmark_by_time)
    benchmark = tuple(benchmark_by_time[bar.timestamp] for bar in stock)
    stock = stock[-120:]
    benchmark = benchmark[-120:]
    if len(stock) < 90:
        print(
            f"[NOT TESTED] Only {len(stock)} aligned daily observations returned; "
            f"{stock_symbol}={raw_stock_count}; VNINDEX={raw_benchmark_count}"
        )
        return 1

    stock20, stock50 = ema20(stock), ema50(stock)
    index20, index50 = ema20(benchmark), ema50(benchmark)
    rs = relative_strength_vs_benchmark(stock, benchmark, 20)
    average_volume = daily_average_volume(stock, 20)
    levels = breakout_levels(stock, 20)
    observations: list[SignalInputs] = []
    for index, bar in enumerate(stock):
        market_bull = (
            index20[index] is not None and index50[index] is not None
            and benchmark[index].close > index20[index] > index50[index]
        )
        stock_trend = (
            stock20[index] is not None and stock50[index] is not None
            and bar.close > stock20[index] > stock50[index]
        )
        volume_proxy = None if average_volume[index] in (None, 0.0) else bar.volume / average_volume[index]
        breakout = levels[index] is not None and bar.close > levels[index].resistance
        exit_triggered = stock20[index] is not None and bar.close < stock20[index]
        observations.append(
            SignalInputs(
                stock_symbol, bar.timestamp, bar.close,
                MarketRegime.BULL if market_bull else MarketRegime.NEUTRAL,
                stock_trend, rs[index], volume_proxy, breakout, exit_triggered,
            )
        )
    engine = SignalEngine(SignalEngineConfig(1.5, 0.0, 0))
    _, report = run_backtest(engine, observations)
    days = (report.end_timestamp - report.start_timestamp) // 86_400
    print(
        f"[PASS] BACKTEST ENGINE VALIDATION; symbol={stock_symbol}; "
        f"aligned_bars={len(stock)}; calendar_days={days}"
    )
    print(format_performance(report))
    print("LIMITATION: ENGINE ONLY; not CL1/ASMF performance or strategy validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

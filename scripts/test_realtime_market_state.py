"""Phase 4 live acceptance harness for FPT + ACB normalized market state."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
import threading
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.market_state import LatestMarketState
from data.models import TradeTick
from data.vietcap.client import VietcapRealtimeClient
from data.vietcap.pipeline import MatchPriceStatePipeline

SYMBOLS = ("FPT", "ACB")


class DistinctTickTracker:
    """Track distinct normalized ticks required for live acceptance."""

    def __init__(self, symbols: tuple[str, ...], minimum: int) -> None:
        if minimum < 1:
            raise ValueError("minimum must be positive")
        self._minimum = minimum
        self._identities = {symbol: set() for symbol in symbols}

    def record(self, tick: TradeTick) -> None:
        """Record one expected tick identity."""
        if tick.symbol not in self._identities:
            raise ValueError(f"Unexpected tracked symbol: {tick.symbol}")
        self._identities[tick.symbol].add(tick_identity(tick))

    @property
    def complete(self) -> bool:
        """Whether every symbol has the required distinct tick count."""
        return all(
            len(identities) >= self._minimum
            for identities in self._identities.values()
        )

    def counts(self) -> dict[str, int]:
        """Return distinct tick counts per symbol."""
        return {
            symbol: len(identities)
            for symbol, identities in self._identities.items()
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate normalized realtime state for FPT and ACB."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=60.0,
        help="Maximum seconds to wait for changing ticks from both symbols.",
    )
    parser.add_argument(
        "--min-updates-per-symbol",
        type=int,
        default=2,
        help="Minimum distinct valid ticks required for each symbol.",
    )
    parser.add_argument(
        "--engineio-logs",
        action="store_true",
        help="Enable Socket.IO and Engine.IO protocol logs.",
    )
    args = parser.parse_args()
    if args.hold_seconds <= 0:
        parser.error("--hold-seconds must be positive")
    if args.min_updates_per_symbol < 2:
        parser.error(
            "--min-updates-per-symbol must be at least 2 to prove changing ticks"
        )
    return args


def tick_identity(tick: TradeTick) -> tuple[object, ...]:
    """Return normalized fields that distinguish changing trade ticks."""
    return (
        tick.exchange_time,
        tick.price,
        tick.volume,
        tick.accumulated_volume,
        tick.accumulated_value,
    )


def print_tick(tick: TradeTick) -> None:
    """Print one normalized trade tick."""
    print(
        f"[{tick.exchange_time or 'unknown-time'}] {tick.symbol} "
        f"price={tick.price:.2f} "
        f"volume={tick.volume:,.0f} "
        f"accumulated_volume={tick.accumulated_volume:,.0f} "
        f"accumulated_value={tick.accumulated_value:,.0f}"
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, SYMBOLS)
    client = VietcapRealtimeClient(engineio_logger=args.engineio_logs)
    tracker = DistinctTickTracker(SYMBOLS, args.min_updates_per_symbol)
    success = threading.Event()
    first_event = True

    def handle_match_price(payload: object) -> None:
        nonlocal first_event
        if first_event:
            payload_size = (
                len(payload)
                if isinstance(payload, (bytes, bytearray, memoryview))
                else None
            )
            print(
                f"[EVENT] type={type(payload).__name__} "
                f"size={payload_size if payload_size is not None else 'unknown'}"
            )
            first_event = False

        tick = pipeline.handle(payload)
        if tick is None:
            return

        print_tick(tick)
        tracker.record(tick)
        if tracker.complete:
            success.set()

    client.on_match_price(handle_match_price)
    try:
        info = client.connect()
        print(f"[CONNECTED] sid={info.sid} transport={info.transport}")
        client.subscribe_match_price(SYMBOLS)
        print('[SUBSCRIBED] event=w-match-price payload={"symbols":["FPT","ACB"]}')

        deadline = time.monotonic() + args.hold_seconds
        while not success.is_set() and time.monotonic() < deadline:
            client.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        counts = tracker.counts()
        cached = sorted(state.snapshot())
        if not success.is_set():
            print(f"[INCOMPLETE] distinct_ticks={counts} cached_symbols={cached}")
            return 2

        print(f"[PASS] distinct_ticks={counts} cached_symbols={cached}")
        return 0
    except KeyboardInterrupt:
        log.info("Realtime market-state test interrupted")
        return 130
    except Exception:
        log.exception("Realtime FPT + ACB market-state test failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

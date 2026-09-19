"""Phase 5 live acceptance harness for the normalized VNINDEX snapshot."""

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

from data.market_state import LatestIndexState
from data.models import IndexSnapshot
from data.vietcap.client import VietcapRealtimeClient
from data.vietcap.constants import VNINDEX_SYMBOL
from data.vietcap.pipeline import IndexStatePipeline

SYMBOLS = (VNINDEX_SYMBOL,)


class DistinctIndexTracker:
    """Track distinct normalized index snapshots required for acceptance."""

    def __init__(self, symbols: tuple[str, ...], minimum: int) -> None:
        if minimum < 1:
            raise ValueError("minimum must be positive")
        self._minimum = minimum
        self._identities = {symbol.upper(): set() for symbol in symbols}

    def record(self, snapshot: IndexSnapshot) -> None:
        """Record one expected index snapshot identity."""
        if snapshot.symbol not in self._identities:
            raise ValueError(f"Unexpected tracked symbol: {snapshot.symbol}")
        self._identities[snapshot.symbol].add(snapshot_identity(snapshot))

    @property
    def complete(self) -> bool:
        """Whether every index has the required distinct snapshot count."""
        return all(
            len(identities) >= self._minimum
            for identities in self._identities.values()
        )

    def counts(self) -> dict[str, int]:
        """Return distinct snapshot counts per index."""
        return {
            symbol: len(identities)
            for symbol, identities in self._identities.items()
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate normalized realtime state for VNINDEX."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=60.0,
        help="Maximum seconds to wait for changing VNINDEX snapshots.",
    )
    parser.add_argument(
        "--min-updates-per-symbol",
        type=int,
        default=2,
        help="Minimum distinct valid snapshots required for each index.",
    )
    parser.add_argument(
        "--engineio-logs",
        action="store_true",
        help="Enable Socket.IO and Engine.IO protocol logs.",
    )
    parser.add_argument(
        "--raw-debug",
        action="store_true",
        help="Log bounded payload metadata without logging binary content.",
    )
    parser.add_argument(
        "--raw-debug-event-limit",
        type=int,
        default=20,
        help="Maximum raw-debug metadata records per market event.",
    )
    args = parser.parse_args()
    if args.hold_seconds <= 0:
        parser.error("--hold-seconds must be positive")
    if args.min_updates_per_symbol < 2:
        parser.error(
            "--min-updates-per-symbol must be at least 2 to prove changing data"
        )
    if args.raw_debug_event_limit < 1:
        parser.error("--raw-debug-event-limit must be at least 1")
    return args


def snapshot_identity(snapshot: IndexSnapshot) -> tuple[object, ...]:
    """Return normalized fields that distinguish changing index snapshots."""
    return (
        snapshot.exchange_time,
        snapshot.value,
        snapshot.total_volume,
        snapshot.total_value,
        snapshot.advances,
        snapshot.declines,
        snapshot.unchanged,
    )


def print_snapshot(snapshot: IndexSnapshot) -> None:
    """Print one normalized index snapshot."""
    print(
        f"[{snapshot.exchange_time or 'unknown-time'}] {snapshot.symbol} "
        f"value={snapshot.value:.2f} "
        f"change={snapshot.change:+.2f} "
        f"change_percent={snapshot.change_percent:+.2f} "
        f"total_volume={snapshot.total_volume:,.0f} "
        f"total_value={snapshot.total_value:,.0f} "
        f"breadth={snapshot.advances:,.0f}/"
        f"{snapshot.unchanged:,.0f}/"
        f"{snapshot.declines:,.0f} "
        f"ceiling={snapshot.ceiling_count:,.0f} "
        f"floor={snapshot.floor_count:,.0f}"
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(
            logging,
            os.getenv("LOG_LEVEL", "DEBUG" if args.raw_debug else "INFO").upper(),
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, SYMBOLS)
    client = VietcapRealtimeClient(
        engineio_logger=args.engineio_logs,
        raw_debug=args.raw_debug,
        raw_debug_event_limit=args.raw_debug_event_limit,
    )
    tracker = DistinctIndexTracker(SYMBOLS, args.min_updates_per_symbol)
    success = threading.Event()
    first_event = True

    def handle_index(payload: object) -> None:
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

        snapshot = pipeline.handle(payload)
        if snapshot is None:
            return

        print_snapshot(snapshot)
        tracker.record(snapshot)
        if tracker.complete:
            success.set()

    client.on_index(handle_index)
    try:
        info = client.connect()
        print(f"[CONNECTED] sid={info.sid} transport={info.transport}")
        client.subscribe_index(SYMBOLS)
        print('[SUBSCRIBED] event=index payload={"symbols":["VNINDEX"]}')

        deadline = time.monotonic() + args.hold_seconds
        while not success.is_set() and time.monotonic() < deadline:
            client.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        counts = tracker.counts()
        cached = sorted(state.snapshot())
        if not success.is_set():
            print(f"[INCOMPLETE] distinct_snapshots={counts} cached_indices={cached}")
            return 2

        print(f"[PASS] distinct_snapshots={counts} cached_indices={cached}")
        return 0
    except KeyboardInterrupt:
        log.info("Realtime index test interrupted")
        return 130
    except Exception:
        log.exception("Realtime VNINDEX market-state test failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

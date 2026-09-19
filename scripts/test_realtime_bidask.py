"""Phase 6 live acceptance harness for normalized FPT + ACB order books."""

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

from data.market_state import LatestOrderBookState
from data.models import OrderBook
from data.vietcap.client import VietcapRealtimeClient
from data.vietcap.pipeline import BidAskStatePipeline

SYMBOLS = ("FPT", "ACB")


class DistinctOrderBookTracker:
    """Track distinct normalized order books required for live acceptance."""

    def __init__(self, symbols: tuple[str, ...], minimum: int) -> None:
        if minimum < 1:
            raise ValueError("minimum must be positive")
        self._minimum = minimum
        self._identities = {symbol: set() for symbol in symbols}

    def record(self, book: OrderBook) -> None:
        """Record one expected order-book identity."""
        if book.symbol not in self._identities:
            raise ValueError(f"Unexpected tracked symbol: {book.symbol}")
        self._identities[book.symbol].add(order_book_identity(book))

    @property
    def complete(self) -> bool:
        """Whether every symbol has the required distinct book count."""
        return all(
            len(identities) >= self._minimum
            for identities in self._identities.values()
        )

    def counts(self) -> dict[str, int]:
        """Return distinct order-book counts per symbol."""
        return {
            symbol: len(identities)
            for symbol, identities in self._identities.items()
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate normalized realtime order books for FPT and ACB."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=60.0,
        help="Maximum seconds to wait for changing books from both symbols.",
    )
    parser.add_argument(
        "--min-updates-per-symbol",
        type=int,
        default=2,
        help="Minimum distinct valid order books required for each symbol.",
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
            "--min-updates-per-symbol must be at least 2 to prove changing books"
        )
    return args


def order_book_identity(book: OrderBook) -> tuple[object, ...]:
    """Return normalized fields that distinguish changing order books."""
    return (
        book.session,
        tuple((level.price, level.volume) for level in book.bids),
        tuple((level.price, level.volume) for level in book.asks),
    )


def format_side(book: OrderBook, side: str) -> str:
    """Render up to three levels of one side for console output."""
    levels = book.bids if side == "bid" else book.asks
    if not levels:
        return "empty"
    return " ".join(
        f"{level.price:.2f}x{level.volume:,.0f}" for level in levels[:3]
    )


def print_book(book: OrderBook) -> None:
    """Print one normalized order book."""
    print(
        f"[{book.session or 'unknown-session'}] {book.symbol} "
        f"bids({len(book.bids)}): {format_side(book, 'bid')} | "
        f"asks({len(book.asks)}): {format_side(book, 'ask')}"
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, SYMBOLS)
    client = VietcapRealtimeClient(engineio_logger=args.engineio_logs)
    tracker = DistinctOrderBookTracker(SYMBOLS, args.min_updates_per_symbol)
    success = threading.Event()
    first_event = True

    def handle_bid_ask(payload: object) -> None:
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

        book = pipeline.handle(payload)
        if book is None:
            return

        print_book(book)
        tracker.record(book)
        if tracker.complete:
            success.set()

    client.on_bid_ask(handle_bid_ask)
    try:
        info = client.connect()
        print(f"[CONNECTED] sid={info.sid} transport={info.transport}")
        client.subscribe_bid_ask(SYMBOLS)
        print('[SUBSCRIBED] event=w-bid-ask payload={"symbols":["FPT","ACB"]}')

        deadline = time.monotonic() + args.hold_seconds
        while not success.is_set() and time.monotonic() < deadline:
            client.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        counts = tracker.counts()
        cached = sorted(state.snapshot())
        if not success.is_set():
            print(f"[INCOMPLETE] distinct_books={counts} cached_symbols={cached}")
            return 2

        print(f"[PASS] distinct_books={counts} cached_symbols={cached}")
        return 0
    except KeyboardInterrupt:
        log.info("Realtime order-book test interrupted")
        return 130
    except Exception:
        log.exception("Realtime FPT + ACB order-book test failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
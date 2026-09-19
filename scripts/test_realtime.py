"""Phase 3 live test for the FPT match-price stream only."""

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

from data.vietcap.client import VietcapRealtimeClient
from data.vietcap.decoder import decode_match_price
from data.vietcap.proto import price_pb2
from data.vietcap.validation import validate_match_price

SYMBOL = "FPT"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe only FPT to the Vietcap match-price stream."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=60.0,
        help="Maximum seconds to wait for changing FPT ticks.",
    )
    parser.add_argument(
        "--min-updates",
        type=int,
        default=2,
        help="Minimum distinct valid ticks required for success.",
    )
    parser.add_argument(
        "--engineio-logs",
        action="store_true",
        help="Enable Socket.IO and Engine.IO protocol logs.",
    )
    args = parser.parse_args()
    if args.hold_seconds <= 0:
        parser.error("--hold-seconds must be positive")
    if args.min_updates < 2:
        parser.error("--min-updates must be at least 2 to prove changing ticks")
    return args


def tick_identity(message: price_pb2.MatchPriceMessage) -> tuple[object, ...]:
    """Return fields that distinguish changing trade ticks."""
    return (
        message.time,
        message.matchPrice,
        message.matchVol,
        message.accumulatedVolume,
        message.accumulatedValue,
    )


def print_tick(message: price_pb2.MatchPriceMessage) -> None:
    """Print provider fields with normalized terminal labels."""
    print(
        f"[{message.time or 'unknown-time'}] {message.symbol} "
        f"price={message.matchPrice:.2f} "
        f"volume={message.matchVol:,.0f} "
        f"accumulated_volume={message.accumulatedVolume:,.0f} "
        f"accumulated_value={message.accumulatedValue:,.0f}"
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)
    client = VietcapRealtimeClient(engineio_logger=args.engineio_logs)
    distinct_ticks: set[tuple[object, ...]] = set()
    success = threading.Event()
    first_event = True

    def handle_match_price(payload: object) -> None:
        nonlocal first_event
        payload_size = (
            len(payload)
            if isinstance(payload, (bytes, bytearray, memoryview))
            else None
        )
        if first_event:
            log.info(
                "Received match-price event metadata",
                extra={
                    "payload_type": type(payload).__name__,
                    "payload_size": payload_size,
                },
            )
            print(
                f"[EVENT] type={type(payload).__name__} "
                f"size={payload_size if payload_size is not None else 'unknown'}"
            )
            first_event = False

        try:
            message = decode_match_price(payload)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log.exception("Rejected match-price event payload")
            return

        if message.symbol != SYMBOL:
            log.warning(
                "Ignoring unexpected match-price symbol",
                extra={"expected_symbol": SYMBOL, "symbol": message.symbol},
            )
            return

        errors = validate_match_price(message)
        if errors:
            log.warning(
                "Rejected invalid FPT match-price message",
                extra={"symbol": message.symbol, "validation_errors": errors},
            )
            return

        print_tick(message)
        distinct_ticks.add(tick_identity(message))
        if len(distinct_ticks) >= args.min_updates:
            success.set()

    client.on_match_price(handle_match_price)
    try:
        info = client.connect()
        print(f"[CONNECTED] sid={info.sid} transport={info.transport}")
        client.subscribe_match_price((SYMBOL,))
        print('[SUBSCRIBED] event=w-match-price payload={"symbols":["FPT"]}')

        deadline = time.monotonic() + args.hold_seconds
        while not success.is_set() and time.monotonic() < deadline:
            client.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        if not success.is_set():
            print(
                f"[INCOMPLETE] received {len(distinct_ticks)} distinct valid FPT "
                f"tick(s); required {args.min_updates}"
            )
            return 2

        print(f"[PASS] received {len(distinct_ticks)} distinct valid FPT ticks")
        return 0
    except KeyboardInterrupt:
        log.info("Realtime test interrupted")
        return 130
    except Exception:
        log.exception("Realtime FPT test failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

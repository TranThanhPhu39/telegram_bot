"""Phase 7 live acceptance harness for forced transport recovery."""

from __future__ import annotations

import argparse
from collections.abc import Callable
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

SYMBOLS = ("FPT",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate stream recovery after a forced WebSocket interruption."
    )
    parser.add_argument(
        "--stage-timeout",
        type=float,
        default=45.0,
        help="Maximum seconds for each pre-event, reconnect, and post-event stage.",
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
    if args.stage_timeout <= 0:
        parser.error("--stage-timeout must be positive")
    if args.raw_debug_event_limit < 1:
        parser.error("--raw-debug-event-limit must be at least 1")
    return args


def tick_identity(tick: TradeTick) -> tuple[object, ...]:
    """Return fields that distinguish one normalized trade tick."""
    return (
        tick.exchange_time,
        tick.price,
        tick.volume,
        tick.accumulated_volume,
        tick.accumulated_value,
    )


def wait_until(
    client: VietcapRealtimeClient,
    predicate: Callable[[], bool],
    timeout: float,
) -> bool:
    """Wait for a condition while allowing Socket.IO heartbeat processing."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        client.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return bool(predicate())


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
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, SYMBOLS)
    client = VietcapRealtimeClient(
        engineio_logger=args.engineio_logs,
        raw_debug=args.raw_debug,
        raw_debug_event_limit=args.raw_debug_event_limit,
    )
    before_tick = threading.Event()
    after_tick = threading.Event()
    before_identity: tuple[object, ...] | None = None
    after_identity: tuple[object, ...] | None = None

    def handle_match_price(payload: object) -> None:
        nonlocal before_identity, after_identity
        tick = pipeline.handle(payload)
        if tick is None:
            return
        identity = tick_identity(tick)
        generation = client.connection_generation
        print(
            f"[TICK] generation={generation} symbol={tick.symbol} "
            f"time={tick.exchange_time or 'unknown-time'} price={tick.price:.2f} "
            f"volume={tick.volume:,.0f}"
        )
        if generation == 1 and before_identity is None:
            before_identity = identity
            before_tick.set()
        elif generation >= 2:
            after_identity = identity
            after_tick.set()

    client.on_match_price(handle_match_price)
    try:
        info = client.connect()
        print(
            f"[CONNECTED] generation={client.connection_generation} "
            f"sid={info.sid} transport={info.transport}"
        )
        client.subscribe_match_price(SYMBOLS)
        print('[SUBSCRIBED] event=w-match-price payload={"symbols":["FPT"]}')

        if not wait_until(client, before_tick.is_set, args.stage_timeout):
            print("[INCOMPLETE] no valid FPT tick before interruption")
            return 2

        print("[INTERRUPT] closing underlying WebSocket transport")
        client.interrupt_transport()

        reconnected = wait_until(
            client,
            lambda: client.disconnect_count >= 1
            and client.connection_generation >= 2
            and client.connected,
            args.stage_timeout,
        )
        if not reconnected:
            print(
                "[INCOMPLETE] reconnect not observed "
                f"connections={client.connection_generation} "
                f"disconnects={client.disconnect_count}"
            )
            return 2
        print(
            f"[RECONNECTED] generation={client.connection_generation} "
            f"disconnects={client.disconnect_count} subscription=restored"
        )

        if not wait_until(client, after_tick.is_set, args.stage_timeout):
            print("[INCOMPLETE] no valid FPT tick after reconnect")
            return 2

        cached = sorted(state.snapshot())
        print(
            "[PASS] stream_resumed=True subscription_restored=True "
            f"connections={client.connection_generation} "
            f"disconnects={client.disconnect_count} cached_symbols={cached} "
            f"before_after_distinct={before_identity != after_identity}"
        )
        return 0
    except KeyboardInterrupt:
        log.info("Realtime reconnect test interrupted")
        return 130
    except Exception:
        log.exception("Realtime forced-interruption test failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

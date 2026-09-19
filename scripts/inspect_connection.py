"""Connect to Vietcap Socket.IO without subscribing to market streams."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.vietcap.client import VietcapRealtimeClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Vietcap Socket.IO connection only."
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=30.0,
        help="Seconds to keep the connection open for heartbeat observation.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for the initial connection.",
    )
    parser.add_argument(
        "--engineio-logs",
        action="store_true",
        help="Enable python-socketio and Engine.IO protocol logs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = VietcapRealtimeClient(engineio_logger=args.engineio_logs)
    try:
        info = client.connect(timeout=args.connect_timeout)
        print(f"[CONNECTED] sid={info.sid} transport={info.transport}")
        client.sleep(args.hold_seconds)
        if not client.connected:
            raise ConnectionError("Connection closed during smoke-test hold period")
        print(f"[STABLE] connected for {args.hold_seconds:.1f}s")
        return 0
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Connection inspection interrupted")
        return 130
    except Exception:
        logging.getLogger(__name__).exception("Connection inspection failed")
        return 1
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())

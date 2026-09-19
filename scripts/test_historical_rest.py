"""Bounded Phase 8 live probe using user-supplied local credentials."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.vietcap.historical import normalize_gap_chart  # noqa: E402
from data.vietcap.rest import (  # noqa: E402
    VietcapRestClient,
    VietcapRestError,
    VietcapTimeFrame,
)


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    authorization = os.getenv("VIETCAP_AUTHORIZATION", "").strip()
    device_id = os.getenv("VIETCAP_DEVICE_ID", "").strip()
    cookie = os.getenv("VIETCAP_COOKIE", "").strip()
    if not authorization or not device_id or not cookie:
        print(
            "[FAIL] Set VIETCAP_AUTHORIZATION, VIETCAP_DEVICE_ID, and "
            "VIETCAP_COOKIE in .env"
        )
        return 2

    client = VietcapRestClient(
        authorization=authorization,
        device_id=device_id,
        cookie=cookie,
    )
    try:
        payload = client.get_gap_chart(
            ("ACB",),
            time_frame=VietcapTimeFrame.ONE_MINUTE,
            count_back=121,
            # Replay the exact request boundary observed returning HTTP 200 in
            # the browser before generalizing provider-specific date rules.
            to_timestamp=1_789_830_754,
        )
    except VietcapRestError:
        print(
            "[FAIL] Vietcap rejected the authenticated historical request; "
            "refresh all local credentials from the same browser session"
        )
        return 1
    bars = normalize_gap_chart(payload, time_frame=VietcapTimeFrame.ONE_MINUTE)
    if not bars:
        print("[FAIL] Vietcap returned no ACB bars")
        return 1
    print(
        "[PASS] Received and normalized "
        f"{len(bars)} ACB ONE_MINUTE bars; "
        f"range={bars[0].timestamp}..{bars[-1].timestamp}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

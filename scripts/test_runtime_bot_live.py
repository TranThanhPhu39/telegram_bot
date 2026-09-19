"""Bounded live smoke test for the historical-first Telegram runtime."""

import sys

from runtime.bot_service import build_runtime_service_from_env


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    service = build_runtime_service_from_env()
    symbol = service.symbol_overview("ACB")
    market = service.market_overview()
    if "Chưa có dữ liệu" in symbol or "Chưa có dữ liệu" in market:
        print("[FAIL] Runtime did not obtain historical fallback data")
        return 1
    print("[PASS] /soi ACB historical runtime response")
    print(symbol)
    print("[PASS] /market historical runtime response")
    print(market)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

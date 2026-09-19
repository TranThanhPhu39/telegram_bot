"""Subscription payload construction for Vietcap market streams."""

from __future__ import annotations

from collections.abc import Iterable
import json


def build_symbol_subscription(symbols: Iterable[str]) -> str:
    """Build the compact JSON-string payload used by Vietcap subscriptions."""
    normalized = [symbol.strip().upper() for symbol in symbols]
    if not normalized or any(not symbol for symbol in normalized):
        raise ValueError("At least one non-empty symbol is required")
    return json.dumps({"symbols": normalized}, separators=(",", ":"))

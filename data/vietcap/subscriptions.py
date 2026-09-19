"""Subscription payload construction for Vietcap market streams."""

from __future__ import annotations

from collections.abc import Iterable
import json


def normalize_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    """Normalize symbols and remove duplicates while preserving input order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            raise ValueError("At least one non-empty symbol is required")
        if symbol not in seen:
            normalized.append(symbol)
            seen.add(symbol)

    if not normalized:
        raise ValueError("At least one non-empty symbol is required")
    return tuple(normalized)


def build_symbol_subscription(symbols: Iterable[str]) -> str:
    """Build the compact JSON-string payload used by Vietcap subscriptions."""
    normalized = normalize_symbols(symbols)
    return json.dumps({"symbols": normalized}, separators=(",", ":"))

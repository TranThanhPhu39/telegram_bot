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


def normalize_index_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    """Trim and de-duplicate index symbols while preserving provider casing.

    Vietcap index identifiers are case-sensitive on the wire (for example
    ``HNXIndex``), so unlike stock symbols they must not be upper-cased before
    being sent. Duplicates are removed case-insensitively and the first-seen
    spelling is kept.
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = raw_symbol.strip()
        if not symbol:
            raise ValueError("At least one non-empty symbol is required")
        key = symbol.upper()
        if key not in seen:
            normalized.append(symbol)
            seen.add(key)

    if not normalized:
        raise ValueError("At least one non-empty symbol is required")
    return tuple(normalized)


def _dump_symbols(symbols: tuple[str, ...]) -> str:
    """Serialize symbols using the compact JSON shape observed in the frontend."""
    return json.dumps({"symbols": symbols}, separators=(",", ":"))


def build_symbol_subscription(symbols: Iterable[str]) -> str:
    """Build the compact JSON-string payload used by Vietcap subscriptions."""
    return _dump_symbols(normalize_symbols(symbols))


def build_index_subscription(symbols: Iterable[str]) -> str:
    """Build the compact JSON-string payload used by the Vietcap index stream."""
    return _dump_symbols(normalize_index_symbols(symbols))
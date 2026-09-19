"""Tests for Vietcap subscription payloads."""

import pytest

from data.vietcap.subscriptions import (
    build_index_subscription,
    build_symbol_subscription,
    normalize_index_symbols,
    normalize_symbols,
)


def test_build_fpt_subscription_payload() -> None:
    assert build_symbol_subscription(["fpt"]) == '{"symbols":["FPT"]}'


def test_build_fpt_acb_subscription_deduplicates_symbols() -> None:
    symbols = normalize_symbols([" fpt ", "ACB", "fpt", " acb "])

    assert symbols == ("FPT", "ACB")
    assert build_symbol_subscription(symbols) == '{"symbols":["FPT","ACB"]}'


@pytest.mark.parametrize("symbols", [[], [""], ["  "]])
def test_build_symbol_subscription_rejects_empty_symbols(symbols: list[str]) -> None:
    with pytest.raises(ValueError, match="non-empty symbol"):
        build_symbol_subscription(symbols)


def test_build_vnindex_subscription_payload() -> None:
    assert build_index_subscription(["vnindex"]) == '{"symbols":["vnindex"]}'


def test_index_symbols_preserve_provider_casing_and_deduplicate() -> None:
    symbols = normalize_index_symbols([" HNXIndex ", "VNINDEX", "hnxindex"])

    assert symbols == ("HNXIndex", "VNINDEX")
    assert build_index_subscription(symbols) == (
        '{"symbols":["HNXIndex","VNINDEX"]}'
    )


@pytest.mark.parametrize("symbols", [[], [""], ["  "]])
def test_build_index_subscription_rejects_empty_symbols(symbols: list[str]) -> None:
    with pytest.raises(ValueError, match="non-empty symbol"):
        build_index_subscription(symbols)

"""Tests for Vietcap subscription payloads."""

import pytest

from data.vietcap.subscriptions import build_symbol_subscription, normalize_symbols


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

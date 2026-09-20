"""Deterministic tests for selectable CL1 and ASMF strategies."""

import pytest

from data.models import OHLCVBar
from strategy.technical_strategies import (
    StrategyAction,
    adx,
    evaluate_asmf,
    evaluate_cl1,
)


def bars(symbol: str = "FPT", count: int = 260) -> tuple[OHLCVBar, ...]:
    values = []
    for index in range(count):
        close = 100 + index * 0.2 + (index % 5) * 0.05
        values.append(OHLCVBar(symbol, "ONE_DAY", 1_700_000_000 + index * 86_400,
                               close - .2, close + 1, close - 1, close,
                               1_000_000 + index * 1000))
    return tuple(values)


def test_adx_is_aligned_and_finite_after_warmup() -> None:
    values = adx(bars())
    assert len(values) == 260
    assert values[-1] is not None
    assert 0 <= values[-1] <= 100  # type: ignore[operator]


def test_cl1_returns_explainable_result_and_chandelier() -> None:
    result = evaluate_cl1(bars())
    assert result.action in {StrategyAction.WATCH, StrategyAction.BUY, StrategyAction.SELL}
    assert result.stop is not None
    assert result.symbol == "FPT"
    assert result.positive or result.negative


def test_asmf_blocks_buy_when_required_layers_are_missing() -> None:
    result = evaluate_asmf(bars(), bars("VNINDEX"))
    assert result.action is StrategyAction.BLOCKED
    assert result.score is not None
    assert set(result.missing) == {
        "sức mạnh ngành/breadth",
        "chất lượng BCTC theo ngày công bố",
        "dòng tiền khối ngoại/tự doanh",
    }


def test_strategies_reject_short_history() -> None:
    with pytest.raises(ValueError, match="at least 200"):
        evaluate_cl1(bars(count=199))

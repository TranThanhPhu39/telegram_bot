"""Tests for the provider-independent V1 signal lifecycle."""

import json

import pytest

from data.market_regime import MarketRegime
from strategy.signal_engine import (
    SignalEngine,
    SignalEngineConfig,
    SignalInputs,
    SignalState,
)


CONFIG = SignalEngineConfig(
    minimum_rvol=1.5,
    minimum_relative_strength=2.0,
    cooldown_seconds=300,
)


def inputs(timestamp: int, **overrides: object) -> SignalInputs:
    values: dict[str, object] = {
        "symbol": "FPT",
        "timestamp": timestamp,
        "price": 100.0,
        "market_regime": MarketRegime.BULL,
        "stock_trend_confirmed": True,
        "relative_strength": 3.0,
        "rvol": 2.0,
        "breakout": False,
        "exit_triggered": False,
    }
    values.update(overrides)
    return SignalInputs(**values)  # type: ignore[arg-type]


def test_complete_signal_lifecycle_advances_one_state_per_observation() -> None:
    engine = SignalEngine(CONFIG)
    events = [
        engine.evaluate(inputs(100)),
        engine.evaluate(inputs(101, price=101.0)),
        engine.evaluate(inputs(102, price=102.0, breakout=True)),
        engine.evaluate(inputs(103, price=103.0, breakout=True)),
        engine.evaluate(inputs(104, price=104.0, breakout=True)),
        engine.evaluate(inputs(105, price=99.0, exit_triggered=True)),
    ]

    assert [event.to_state for event in events if event is not None] == list(SignalState)
    assert [event.sequence for event in events if event is not None] == [1, 2, 3, 4, 5, 6]
    assert events[0].from_state is None
    assert events[-1].from_state is SignalState.ACTIVE
    assert engine.state(" fpt ") is SignalState.EXIT


def test_watch_waits_until_all_money_flow_confirmations_exist() -> None:
    engine = SignalEngine(CONFIG)
    engine.evaluate(inputs(100, market_regime=MarketRegime.NEUTRAL))

    assert engine.evaluate(inputs(101, market_regime=MarketRegime.NEUTRAL)) is None
    assert engine.evaluate(inputs(102, rvol=1.49)) is None
    assert engine.evaluate(inputs(103, relative_strength=None)) is None
    event = engine.evaluate(inputs(104))

    assert event is not None and event.to_state is SignalState.MONEY_FLOW


def test_money_flow_waits_for_breakout_and_breakout_reconfirms_inputs() -> None:
    engine = SignalEngine(CONFIG)
    engine.evaluate(inputs(100))
    engine.evaluate(inputs(101, price=101.0))

    assert engine.evaluate(inputs(102, price=102.0)) is None
    breakout = engine.evaluate(inputs(103, price=103.0, breakout=True))
    assert breakout is not None and breakout.to_state is SignalState.BREAKOUT
    assert engine.evaluate(inputs(104, price=104.0, breakout=True, rvol=1.0)) is None
    confirmed = engine.evaluate(inputs(105, price=105.0, breakout=True))
    assert confirmed is not None and confirmed.to_state is SignalState.CONFIRMED


def test_duplicate_observation_is_ignored() -> None:
    engine = SignalEngine(CONFIG)
    observation = inputs(100)
    first = engine.evaluate(observation)

    assert first is not None and first.to_state is SignalState.WATCH
    assert engine.evaluate(observation) is None
    assert engine.state("FPT") is SignalState.WATCH


def test_symbols_have_independent_lifecycles() -> None:
    engine = SignalEngine(CONFIG)
    fpt = engine.evaluate(inputs(100))
    acb = engine.evaluate(inputs(100, symbol="ACB", price=20.0))

    assert fpt is not None and acb is not None
    assert fpt.lifecycle == acb.lifecycle == 1
    assert engine.state("FPT") is SignalState.WATCH
    assert engine.state("ACB") is SignalState.WATCH


def test_exit_cooldown_prevents_restart_then_creates_new_lifecycle() -> None:
    engine = SignalEngine(CONFIG)
    engine.evaluate(inputs(100))
    engine.evaluate(inputs(101, price=101.0))
    engine.evaluate(inputs(102, price=102.0, breakout=True))
    engine.evaluate(inputs(103, price=103.0, breakout=True))
    engine.evaluate(inputs(104, price=104.0, breakout=True))
    exit_event = engine.evaluate(inputs(105, price=99.0, exit_triggered=True))
    assert exit_event is not None and exit_event.to_state is SignalState.EXIT

    assert engine.evaluate(inputs(404, price=100.0)) is None
    restarted = engine.evaluate(inputs(405, price=101.0))

    assert restarted is not None
    assert restarted.from_state is None
    assert restarted.to_state is SignalState.WATCH
    assert restarted.lifecycle == 2
    assert restarted.sequence == 1


def test_exit_requires_explicit_exit_condition() -> None:
    engine = SignalEngine(CONFIG)
    for observation in (
        inputs(100),
        inputs(101, price=101.0),
        inputs(102, price=102.0, breakout=True),
        inputs(103, price=103.0, breakout=True),
        inputs(104, price=104.0, breakout=True),
    ):
        engine.evaluate(observation)

    assert engine.evaluate(inputs(105, market_regime=MarketRegime.BEAR)) is None
    assert engine.state("FPT") is SignalState.ACTIVE


def test_reason_payload_is_json_serializable_and_explainable() -> None:
    engine = SignalEngine(CONFIG)
    event = engine.evaluate(
        inputs(
            100,
            market_regime=MarketRegime.BEAR,
            stock_trend_confirmed=False,
            relative_strength=1.0,
            rvol=None,
        )
    )

    assert event is not None
    payload = event.reason.to_payload()
    assert "market regime is BEAR" in payload["negative_factors"]
    assert "stock trend confirmation" in payload["missing_confirmations"]
    assert "RVOL" in payload["missing_confirmations"]
    assert json.loads(json.dumps(payload))["trigger"] == "new symbol"


def test_rejects_out_of_order_input_without_mutating_state() -> None:
    engine = SignalEngine(CONFIG)
    engine.evaluate(inputs(100))

    with pytest.raises(ValueError, match="chronological"):
        engine.evaluate(inputs(99, price=101.0))

    assert engine.state("FPT") is SignalState.WATCH


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": "fpt"},
        {"timestamp": 0},
        {"price": 0.0},
        {"relative_strength": float("nan")},
        {"rvol": -1.0},
        {"stock_trend_confirmed": 1},
    ],
)
def test_signal_inputs_validate_boundaries(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        inputs(100, **overrides)


def test_config_validates_thresholds_and_cooldown() -> None:
    with pytest.raises(ValueError, match="minimum_rvol"):
        SignalEngineConfig(0.0, 1.0, 0)
    with pytest.raises(ValueError, match="relative_strength"):
        SignalEngineConfig(1.0, float("nan"), 0)
    with pytest.raises(ValueError, match="cooldown"):
        SignalEngineConfig(1.0, 1.0, -1)

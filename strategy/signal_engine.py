"""Deterministic V1 signal lifecycle engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from data.market_regime import MarketRegime


class SignalState(str, Enum):
    WATCH = "WATCH"
    MONEY_FLOW = "MONEY_FLOW"
    BREAKOUT = "BREAKOUT"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    EXIT = "EXIT"


@dataclass(frozen=True, slots=True)
class SignalEngineConfig:
    minimum_rvol: float
    minimum_relative_strength: float
    cooldown_seconds: int

    def __post_init__(self) -> None:
        if not isfinite(self.minimum_rvol) or self.minimum_rvol <= 0:
            raise ValueError("minimum_rvol must be finite and positive")
        if not isfinite(self.minimum_relative_strength):
            raise ValueError("minimum_relative_strength must be finite")
        if not isinstance(self.cooldown_seconds, int) or isinstance(
            self.cooldown_seconds, bool
        ):
            raise TypeError("cooldown_seconds must be an integer")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class SignalInputs:
    symbol: str
    timestamp: int
    price: float
    market_regime: MarketRegime
    stock_trend_confirmed: bool
    relative_strength: float | None
    rvol: float | None
    breakout: bool
    exit_triggered: bool

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be non-empty and normalized")
        if not isinstance(self.timestamp, int) or isinstance(self.timestamp, bool):
            raise TypeError("timestamp must be an integer")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be positive")
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be finite and positive")
        if not isinstance(self.market_regime, MarketRegime):
            raise TypeError("market_regime must be a MarketRegime")
        for name in ("stock_trend_confirmed", "breakout", "exit_triggered"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        for name in ("relative_strength", "rvol"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        if self.rvol is not None and self.rvol < 0:
            raise ValueError("rvol must be non-negative when present")


@dataclass(frozen=True, slots=True)
class SignalReason:
    positive_factors: tuple[str, ...]
    negative_factors: tuple[str, ...]
    missing_confirmations: tuple[str, ...]
    trigger: str

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable explanation payload."""
        return {
            "positive_factors": list(self.positive_factors),
            "negative_factors": list(self.negative_factors),
            "missing_confirmations": list(self.missing_confirmations),
            "trigger": self.trigger,
        }


@dataclass(frozen=True, slots=True)
class SignalEvent:
    symbol: str
    lifecycle: int
    sequence: int
    occurred_at: int
    from_state: SignalState | None
    to_state: SignalState
    price: float
    reason: SignalReason


@dataclass(slots=True)
class _SymbolState:
    state: SignalState
    lifecycle: int
    sequence: int
    last_timestamp: int
    last_input: SignalInputs
    exited_at: int | None = None


class SignalEngine:
    """Advance each symbol through the V1 lifecycle, at most once per input."""

    def __init__(self, config: SignalEngineConfig) -> None:
        if not isinstance(config, SignalEngineConfig):
            raise TypeError("config must be a SignalEngineConfig")
        self.config = config
        self._symbols: dict[str, _SymbolState] = {}

    def state(self, symbol: str) -> SignalState | None:
        normalized = _normalize_symbol(symbol)
        record = self._symbols.get(normalized)
        return None if record is None else record.state

    def evaluate(self, inputs: SignalInputs) -> SignalEvent | None:
        """Evaluate one observation and emit only a lifecycle transition."""
        if not isinstance(inputs, SignalInputs):
            raise TypeError("inputs must be SignalInputs")
        record = self._symbols.get(inputs.symbol)
        if record is None:
            event = self._event(inputs, 1, 1, None, SignalState.WATCH, "new symbol")
            self._symbols[inputs.symbol] = _SymbolState(
                SignalState.WATCH, 1, 1, inputs.timestamp, inputs
            )
            return event
        if inputs.timestamp < record.last_timestamp:
            raise ValueError("signal inputs must be chronological per symbol")
        if inputs == record.last_input:
            return None

        previous = record.state
        target, trigger = self._next_state(record, inputs)
        record.last_timestamp = inputs.timestamp
        record.last_input = inputs
        if target is None:
            return None

        if previous is SignalState.EXIT and target is SignalState.WATCH:
            record.lifecycle += 1
            record.sequence = 1
            from_state = None
        else:
            record.sequence += 1
            from_state = previous
        record.state = target
        record.exited_at = inputs.timestamp if target is SignalState.EXIT else None
        return self._event(
            inputs,
            record.lifecycle,
            record.sequence,
            from_state,
            target,
            trigger,
        )

    def _next_state(
        self, record: _SymbolState, inputs: SignalInputs
    ) -> tuple[SignalState | None, str]:
        confirmed = self._confirmations(inputs)
        if record.state is SignalState.WATCH and confirmed:
            return SignalState.MONEY_FLOW, "money-flow confirmations met"
        if record.state is SignalState.MONEY_FLOW and inputs.breakout:
            return SignalState.BREAKOUT, "price exceeded prior breakout resistance"
        if record.state is SignalState.BREAKOUT and confirmed and inputs.breakout:
            return SignalState.CONFIRMED, "breakout retained all confirmations"
        if record.state is SignalState.CONFIRMED and confirmed:
            return SignalState.ACTIVE, "confirmed setup activated"
        if record.state is SignalState.ACTIVE and inputs.exit_triggered:
            return SignalState.EXIT, "explicit exit condition triggered"
        if record.state is SignalState.EXIT:
            assert record.exited_at is not None
            cooldown_end = record.exited_at + self.config.cooldown_seconds
            if inputs.timestamp >= cooldown_end and not inputs.exit_triggered:
                return SignalState.WATCH, "cooldown completed; new lifecycle"
        return None, "no transition"

    def _confirmations(self, inputs: SignalInputs) -> bool:
        return (
            inputs.market_regime is MarketRegime.BULL
            and inputs.stock_trend_confirmed
            and inputs.relative_strength is not None
            and inputs.relative_strength >= self.config.minimum_relative_strength
            and inputs.rvol is not None
            and inputs.rvol >= self.config.minimum_rvol
        )

    def _event(
        self,
        inputs: SignalInputs,
        lifecycle: int,
        sequence: int,
        from_state: SignalState | None,
        to_state: SignalState,
        trigger: str,
    ) -> SignalEvent:
        positives: list[str] = []
        negatives: list[str] = []
        missing: list[str] = []
        if inputs.market_regime is MarketRegime.BULL:
            positives.append("market regime is BULL")
        elif inputs.market_regime is MarketRegime.BEAR:
            negatives.append("market regime is BEAR")
        else:
            missing.append("BULL market regime")
        if inputs.stock_trend_confirmed:
            positives.append("stock trend confirmed")
        else:
            missing.append("stock trend confirmation")
        _numeric_factor(
            "relative strength",
            inputs.relative_strength,
            self.config.minimum_relative_strength,
            positives,
            negatives,
            missing,
        )
        _numeric_factor(
            "RVOL",
            inputs.rvol,
            self.config.minimum_rvol,
            positives,
            negatives,
            missing,
        )
        if inputs.breakout:
            positives.append("breakout confirmed")
        else:
            missing.append("breakout confirmation")
        if inputs.exit_triggered:
            negatives.append("exit condition triggered")
        return SignalEvent(
            symbol=inputs.symbol,
            lifecycle=lifecycle,
            sequence=sequence,
            occurred_at=inputs.timestamp,
            from_state=from_state,
            to_state=to_state,
            price=inputs.price,
            reason=SignalReason(tuple(positives), tuple(negatives), tuple(missing), trigger),
        )


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _numeric_factor(
    name: str,
    value: float | None,
    threshold: float,
    positives: list[str],
    negatives: list[str],
    missing: list[str],
) -> None:
    if value is None:
        missing.append(name)
    elif value >= threshold:
        positives.append(f"{name}={value:.6f} >= {threshold:.6f}")
    else:
        negatives.append(f"{name}={value:.6f} < {threshold:.6f}")

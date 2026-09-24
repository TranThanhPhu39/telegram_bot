"""Chronological long-only execution and cash accounting for strategy backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite

from data.models import OHLCVBar
from strategy.technical_strategies import StrategyAction, StrategyResult


class EntryMode(str, Enum):
    NEXT_OPEN = "OPEN_T_PLUS_1"


class AllocationMode(str, Enum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"


class FillSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class BacktestExecutionConfig:
    """All execution assumptions; settlement is deliberately caller-supplied."""

    settlement_sessions: int
    entry_mode: EntryMode = EntryMode.NEXT_OPEN
    commission_rate: float = 0.0015
    sell_tax_rate: float = 0.0010
    slippage_rate: float = 0.0020
    lot_size: int = 100
    initial_capital: float = 500_000_000.0
    allocation_mode: AllocationMode = AllocationMode.EQUAL_WEIGHT

    def __post_init__(self) -> None:
        if self.entry_mode is not EntryMode.NEXT_OPEN:
            raise ValueError("only OPEN_T_PLUS_1 is supported")
        if self.allocation_mode is not AllocationMode.EQUAL_WEIGHT:
            raise ValueError("only EQUAL_WEIGHT is supported")
        if not isinstance(self.settlement_sessions, int) or self.settlement_sessions < 0:
            raise ValueError("settlement_sessions must be a non-negative integer")
        if not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        if not isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be finite and positive")
        for name in ("commission_rate", "sell_tax_rate", "slippage_rate"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must satisfy 0 <= value < 1")


@dataclass(frozen=True, slots=True)
class BacktestFill:
    symbol: str
    side: FillSide
    signal_timestamp: int
    fill_timestamp: int
    quantity: int
    price: float
    gross_value: float
    commission: float
    sell_tax: float
    slippage_cost: float


@dataclass(frozen=True, slots=True)
class OpenPosition:
    symbol: str
    quantity: int
    entry_timestamp: int
    entry_session_index: int
    sellable_session_index: int
    entry_price: float
    entry_commission: float

    @property
    def entry_cost(self) -> float:
        return self.quantity * self.entry_price + self.entry_commission


@dataclass(frozen=True, slots=True)
class ExecutedTrade:
    symbol: str
    entry_timestamp: int
    exit_timestamp: int
    quantity: int
    entry_price: float
    exit_price: float
    gross_return_percent: float
    net_return_percent: float
    total_costs: float
    realized_pnl: float
    holding_sessions: int


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: int
    cash: float
    market_value: float
    equity: float
    exposure_percent: float


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    initial_capital: float
    final_cash: float
    fills: tuple[BacktestFill, ...]
    trades: tuple[ExecutedTrade, ...]
    open_positions: tuple[OpenPosition, ...]
    equity_curve: tuple[EquityPoint, ...]
    unfilled_order_count: int


@dataclass(frozen=True, slots=True)
class _PendingOrder:
    symbol: str
    side: FillSide
    signal_timestamp: int
    target_index: int


def simulate_execution(
    histories: Mapping[str, Sequence[OHLCVBar]],
    decisions: Mapping[str, Sequence[StrategyResult]],
    config: BacktestExecutionConfig,
) -> ExecutionResult:
    if not isinstance(config, BacktestExecutionConfig):
        raise TypeError("config must be a BacktestExecutionConfig")
    checked = _validate_histories(histories)
    if not checked:
        raise ValueError("execution requires at least one symbol history")
    symbols = tuple(sorted(checked))
    allocation = config.initial_capital / len(symbols)
    indexes = {
        symbol: {bar.timestamp: index for index, bar in enumerate(history)}
        for symbol, history in checked.items()
    }
    decisions_by_time: dict[int, list[StrategyResult]] = {}
    for symbol, values in decisions.items():
        if symbol not in checked:
            raise ValueError(f"decision symbol {symbol} has no execution history")
        for decision in values:
            if decision.symbol != symbol or decision.timestamp not in indexes[symbol]:
                raise ValueError("decision must match a completed bar in its symbol history")
            decisions_by_time.setdefault(decision.timestamp, []).append(decision)

    bars_by_time: dict[int, dict[str, OHLCVBar]] = {}
    for symbol, history in checked.items():
        for bar in history:
            bars_by_time.setdefault(bar.timestamp, {})[symbol] = bar

    cash = config.initial_capital
    positions: dict[str, OpenPosition] = {}
    pending: dict[str, _PendingOrder] = {}
    fills: list[BacktestFill] = []
    trades: list[ExecutedTrade] = []
    equity_curve: list[EquityPoint] = []
    latest_close: dict[str, float] = {}
    unfilled = 0

    for timestamp in sorted(bars_by_time):
        current_bars = bars_by_time[timestamp]
        due = [order for order in pending.values()
               if checked[order.symbol][order.target_index].timestamp == timestamp]
        for order in sorted(due, key=lambda item: (item.side is FillSide.BUY, item.symbol)):
            bar = current_bars[order.symbol]
            if order.side is FillSide.SELL:
                position = positions.get(order.symbol)
                if position is None:
                    pending.pop(order.symbol, None)
                    continue
                price = _fill_price(bar, order.side, config.slippage_rate)
                gross = position.quantity * price
                commission = gross * config.commission_rate
                sell_tax = gross * config.sell_tax_rate
                proceeds = gross - commission - sell_tax
                cash += proceeds
                entry_gross = position.quantity * position.entry_price
                realized = proceeds - position.entry_cost
                gross_return = (price / position.entry_price - 1.0) * 100.0
                net_return = realized / position.entry_cost * 100.0
                fills.append(BacktestFill(
                    order.symbol, FillSide.SELL, order.signal_timestamp, timestamp,
                    position.quantity, price, gross, commission, sell_tax,
                    abs(price - bar.open) * position.quantity,
                ))
                trades.append(ExecutedTrade(
                    order.symbol, position.entry_timestamp, timestamp,
                    position.quantity, position.entry_price, price,
                    gross_return, net_return,
                    position.entry_commission + commission + sell_tax,
                    realized, indexes[order.symbol][timestamp] - position.entry_session_index,
                ))
                del positions[order.symbol]
            else:
                price = _fill_price(bar, order.side, config.slippage_rate)
                budget = min(cash, allocation)
                per_share_cash = price * (1.0 + config.commission_rate)
                raw_quantity = int(budget / per_share_cash)
                quantity = raw_quantity // config.lot_size * config.lot_size
                if quantity <= 0:
                    unfilled += 1
                    pending.pop(order.symbol, None)
                    continue
                gross = quantity * price
                commission = gross * config.commission_rate
                cash -= gross + commission
                entry_index = indexes[order.symbol][timestamp]
                positions[order.symbol] = OpenPosition(
                    order.symbol, quantity, timestamp, entry_index,
                    entry_index + config.settlement_sessions, price, commission,
                )
                fills.append(BacktestFill(
                    order.symbol, FillSide.BUY, order.signal_timestamp, timestamp,
                    quantity, price, gross, commission, 0.0,
                    abs(price - bar.open) * quantity,
                ))
            pending.pop(order.symbol, None)

        latest_close.update({symbol: bar.close for symbol, bar in current_bars.items()})
        for decision in sorted(decisions_by_time.get(timestamp, ()), key=lambda item: item.symbol):
            symbol = decision.symbol
            index = indexes[symbol][timestamp]
            history = checked[symbol]
            if decision.action is StrategyAction.BUY and symbol not in positions and symbol not in pending:
                target = index + 1
                if target >= len(history):
                    unfilled += 1
                else:
                    pending[symbol] = _PendingOrder(symbol, FillSide.BUY, timestamp, target)
            elif decision.action is StrategyAction.SELL and symbol in positions and symbol not in pending:
                position = positions[symbol]
                target = max(index + 1, position.sellable_session_index)
                if target >= len(history):
                    unfilled += 1
                else:
                    pending[symbol] = _PendingOrder(symbol, FillSide.SELL, timestamp, target)

        market_value = sum(
            position.quantity * latest_close[position.symbol]
            for position in positions.values()
            if position.symbol in latest_close
        )
        equity = cash + market_value
        exposure = market_value / equity * 100.0 if equity > 0 else 0.0
        equity_curve.append(EquityPoint(timestamp, cash, market_value, equity, exposure))

    unfilled += len(pending)
    return ExecutionResult(
        config.initial_capital, cash, tuple(fills), tuple(trades),
        tuple(positions[symbol] for symbol in sorted(positions)),
        tuple(equity_curve), unfilled,
    )


def _fill_price(bar: OHLCVBar, side: FillSide, slippage_rate: float) -> float:
    raw = bar.open * (1.0 + slippage_rate if side is FillSide.BUY else 1.0 - slippage_rate)
    return min(bar.high, max(bar.low, raw))


def _validate_histories(
    histories: Mapping[str, Sequence[OHLCVBar]],
) -> dict[str, tuple[OHLCVBar, ...]]:
    result: dict[str, tuple[OHLCVBar, ...]] = {}
    for key, values in histories.items():
        symbol = key.strip().upper()
        bars = tuple(values)
        if not bars:
            raise ValueError(f"{symbol} execution history is empty")
        if any(bar.symbol != symbol or bar.timeframe != "ONE_DAY" for bar in bars):
            raise ValueError("execution histories must be ONE_DAY bars grouped by symbol")
        if any(left.timestamp >= right.timestamp for left, right in zip(bars, bars[1:])):
            raise ValueError("execution histories must be strictly chronological")
        result[symbol] = bars
    return result

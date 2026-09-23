"""EPS(TTM)/P/E/P/B/BVPS are derived, never fabricated, from raw inputs only."""

from datetime import date

import pytest

from fundamentals.valuation import (
    ValuationSnapshot,
    compute_valuation,
    load_valuation_csv,
)


def test_compute_valuation_with_all_inputs_present() -> None:
    metrics = compute_valuation(
        price=20_000.0,
        shares_outstanding=1_000_000.0,
        ttm_net_profit=2_000_000_000.0,
        equity=10_000_000_000.0,
    )
    assert metrics.eps_ttm == 2_000.0
    assert metrics.bvps == 10_000.0
    assert metrics.pe == 10.0
    assert metrics.pb == 2.0


@pytest.mark.parametrize(
    "overrides",
    [
        dict(price=None),
        dict(shares_outstanding=None),
        dict(ttm_net_profit=None),
        dict(equity=None),
        dict(shares_outstanding=0.0),
    ],
)
def test_compute_valuation_never_guesses_a_missing_input(overrides: dict) -> None:
    base = dict(
        price=20_000.0,
        shares_outstanding=1_000_000.0,
        ttm_net_profit=2_000_000_000.0,
        equity=10_000_000_000.0,
    )
    base.update(overrides)
    metrics = compute_valuation(**base)
    # Whatever the missing input breaks, nothing downstream of it should be
    # silently filled in -- at least one metric must be None.
    assert None in (metrics.eps_ttm, metrics.bvps, metrics.pe, metrics.pb)


def test_compute_valuation_negative_ttm_profit_gives_no_pe() -> None:
    # A loss-making TTM window: EPS is still reportable (negative), but a P/E
    # off a negative EPS is not a meaningful multiple, so it must stay None.
    metrics = compute_valuation(
        price=20_000.0,
        shares_outstanding=1_000_000.0,
        ttm_net_profit=-500_000_000.0,
        equity=10_000_000_000.0,
    )
    assert metrics.eps_ttm == -500.0
    assert metrics.pe is None
    assert metrics.bvps == 10_000.0
    assert metrics.pb == 2.0


def test_compute_valuation_no_inputs_returns_all_none() -> None:
    metrics = compute_valuation(
        price=None, shares_outstanding=None, ttm_net_profit=None, equity=None
    )
    assert metrics.eps_ttm is None
    assert metrics.pe is None
    assert metrics.pb is None
    assert metrics.bvps is None


def test_valuation_csv_loads_raw_inputs_only(tmp_path) -> None:
    path = tmp_path / "valuation.csv"
    path.write_text(
        "symbol,as_of_date,source,price,shares_outstanding\n"
        "fpt,2026-06-30,vietcap-eod,95000,1200000000\n",
        encoding="utf-8",
    )
    result = load_valuation_csv(path)
    assert result == (
        ValuationSnapshot(
            symbol="FPT",
            as_of_date=date(2026, 6, 30),
            source="vietcap-eod",
            price=95_000.0,
            shares_outstanding=1_200_000_000.0,
        ),
    )


def test_valuation_csv_rejects_precomputed_multiples_schema(tmp_path) -> None:
    path = tmp_path / "valuation.csv"
    path.write_text(
        "symbol,as_of_date,source,eps,pe,pb\n"
        "fpt,2026-06-30,vietcap-eod,5000,15,2.5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_valuation_csv(path)


def test_valuation_csv_blank_shares_outstanding_stays_none(tmp_path) -> None:
    path = tmp_path / "valuation.csv"
    path.write_text(
        "symbol,as_of_date,source,price,shares_outstanding\n"
        "fpt,2026-06-30,vietcap-eod,95000,\n",
        encoding="utf-8",
    )
    result = load_valuation_csv(path)
    assert result[0].price == 95_000.0
    assert result[0].shares_outstanding is None

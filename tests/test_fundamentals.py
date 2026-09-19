"""Tests for the Phase 17 CSV source and fundamental context filter."""

from datetime import date

import pytest

from fundamentals.csv_source import load_fundamental_csv
from fundamentals.filter import (
    FundamentalFilterConfig, FundamentalStatus, apply_fundamental_filter,
    assess_fundamentals,
)
from fundamentals.models import FundamentalSnapshot
from scanner.universe import ScreenedSymbol


CONFIG = FundamentalFilterConfig(1.0, 20.0, 3.0, 10.0, 0.0, 0.0)


def snapshot(**overrides: object) -> FundamentalSnapshot:
    values: dict[str, object] = dict(
        symbol="FPT", as_of_date=date(2026, 6, 30), source="licensed-export-2026Q2",
        eps=5_000.0, pe=15.0, pb=2.5, roe_percent=18.0,
        revenue_growth_percent=12.0, profit_growth_percent=15.0,
    )
    values.update(overrides)
    return FundamentalSnapshot(**values)  # type: ignore[arg-type]


def test_all_fundamental_fields_pass_and_export_context() -> None:
    result = assess_fundamentals(snapshot(), CONFIG)
    assert result.status is FundamentalStatus.PASS
    assert len(result.positive_factors) == 6
    assert result.negative_factors == ()
    assert result.missing_fields == ()
    assert result.to_context()["source"] == "licensed-export-2026Q2"


@pytest.mark.parametrize(
    ("field", "value"),
    [("eps", 0.0), ("pe", 21.0), ("pb", 3.1), ("roe_percent", 9.9),
     ("revenue_growth_percent", -0.1), ("profit_growth_percent", -0.1)],
)
def test_each_failed_metric_produces_fail_context(field: str, value: float) -> None:
    result = assess_fundamentals(snapshot(**{field: value}), CONFIG)
    assert result.status is FundamentalStatus.FAIL
    assert field in result.negative_factors[0]


def test_missing_metric_is_insufficient_not_automatic_fail() -> None:
    result = assess_fundamentals(snapshot(pe=None), CONFIG)
    assert result.status is FundamentalStatus.INSUFFICIENT_DATA
    assert result.missing_fields == ("pe",)


def test_filter_is_separate_from_signal_engine_and_configurable_for_missing_data() -> None:
    screened = (
        ScreenedSymbol("FPT", "HOSE", 1, 1, 20),
        ScreenedSymbol("ACB", "HOSE", 1, 1, 20),
        ScreenedSymbol("HPG", "HOSE", 1, 1, 20),
    )
    assessments = {
        "FPT": assess_fundamentals(snapshot(), CONFIG),
        "ACB": assess_fundamentals(snapshot(symbol="ACB", pe=30.0), CONFIG),
        "HPG": assess_fundamentals(snapshot(symbol="HPG", pe=None), CONFIG),
    }
    assert [item.symbol for item in apply_fundamental_filter(screened, assessments)] == ["FPT"]
    assert [item.symbol for item in apply_fundamental_filter(
        screened, assessments, include_insufficient=True
    )] == ["FPT", "HPG"]


def test_csv_source_loads_all_metrics_and_blank_values(tmp_path) -> None:
    path = tmp_path / "fundamentals.csv"
    path.write_text(
        "symbol,as_of_date,source,eps,pe,pb,roe_percent,revenue_growth_percent,profit_growth_percent\n"
        "fpt,2026-06-30,licensed-export,5000,15,2.5,18,12,\n",
        encoding="utf-8",
    )
    result = load_fundamental_csv(path)
    assert result == (snapshot(source="licensed-export", profit_growth_percent=None),)


def test_csv_rejects_schema_duplicates_dates_and_numbers(tmp_path) -> None:
    path = tmp_path / "fundamentals.csv"
    path.write_text("symbol,wrong\nFPT,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        load_fundamental_csv(path)

    header = "symbol,as_of_date,source,eps,pe,pb,roe_percent,revenue_growth_percent,profit_growth_percent\n"
    path.write_text(header + "FPT,bad-date,source,1,2,3,4,5,6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="as_of_date"):
        load_fundamental_csv(path)

    path.write_text(header + "FPT,2026-01-01,source,bad,2,3,4,5,6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="eps"):
        load_fundamental_csv(path)

    path.write_text(
        header + "FPT,2026-01-01,source,1,2,3,4,5,6\n"
        "FPT,2026-02-01,source,1,2,3,4,5,6\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_fundamental_csv(path)


def test_snapshot_requires_provenance_and_finite_metrics() -> None:
    with pytest.raises(ValueError, match="provenance"):
        snapshot(source="")
    with pytest.raises(ValueError, match="finite"):
        snapshot(roe_percent=float("nan"))


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        FundamentalFilterConfig(0, 20, 3, 10, 0, float("nan"))
    with pytest.raises(ValueError, match="positive"):
        FundamentalFilterConfig(0, 0, 3, 10, 0, 0)

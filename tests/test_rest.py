"""Tests for Vietcap REST acquisition."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from data.vietcap.rest import (
    VietcapRestClient,
    VietcapRestError,
    normalize_stock_symbol,
)


class FakeResponse:
    def __init__(
        self,
        payload: object = None,
        *,
        request_error: requests.RequestException | None = None,
        json_error: ValueError | None = None,
    ) -> None:
        self.payload = payload
        self.request_error = request_error
        self.json_error = json_error

    def raise_for_status(self) -> None:
        if self.request_error is not None:
            raise self.request_error

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        return self.response

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        return self.response


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("fpt", "FPT"), (" ACB ", "ACB"), ("vn30", "VN30")],
)
def test_normalize_stock_symbol(raw: str, expected: str) -> None:
    assert normalize_stock_symbol(raw) == expected


@pytest.mark.parametrize("invalid", ["", " ", "FPT/../../token", "FPT?x=1"])
def test_normalize_stock_symbol_rejects_unsafe_values(invalid: str) -> None:
    with pytest.raises(ValueError, match="ASCII letters and digits"):
        normalize_stock_symbol(invalid)


def test_get_quote_uses_normalized_symbol_timeout_and_json_accept_header() -> None:
    session = FakeSession(FakeResponse({"symbol": "FPT", "price": 103.2}))
    client = VietcapRestClient(
        base_url="https://example.test/",
        timeout=7.5,
        session=session,
    )

    result = client.get_quote(" fpt ")

    assert result == {"symbol": "FPT", "price": 103.2}
    assert session.get_calls == [
        (
            "https://example.test/api/price/v1/w/priceboard/ticker/price/FPT",
            {"headers": {"Accept": "application/json"}, "timeout": 7.5},
        )
    ]


def test_get_quote_returns_a_detached_dict() -> None:
    source = {"symbol": "FPT"}
    client = VietcapRestClient(session=FakeSession(FakeResponse(source)))

    result = client.get_quote("FPT")
    result["symbol"] = "ACB"

    assert source == {"symbol": "FPT"}


def test_get_quote_wraps_http_errors() -> None:
    response = FakeResponse(request_error=requests.HTTPError("HTTP 503"))
    client = VietcapRestClient(session=FakeSession(response))

    with pytest.raises(VietcapRestError, match="Failed to fetch.*FPT"):
        client.get_quote("FPT")


def test_get_quote_wraps_invalid_json() -> None:
    response = FakeResponse(
        json_error=requests.exceptions.JSONDecodeError("invalid JSON", "x", 0)
    )
    client = VietcapRestClient(session=FakeSession(response))

    with pytest.raises(VietcapRestError, match="Invalid Vietcap quote JSON"):
        client.get_quote("FPT")


@pytest.mark.parametrize("payload", [None, [], "not-an-object"])
def test_get_quote_rejects_non_object_json(payload: object) -> None:
    client = VietcapRestClient(session=FakeSession(FakeResponse(payload)))

    with pytest.raises(VietcapRestError, match="Invalid Vietcap quote response"):
        client.get_quote("FPT")


@pytest.mark.parametrize("timeout", [0, -1])
def test_rest_client_rejects_non_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        VietcapRestClient(timeout=timeout)


def test_get_gap_chart_uses_exact_post_contract() -> None:
    session = FakeSession(FakeResponse({"t": [1, 2], "o": [25.0, 25.2]}))
    client = VietcapRestClient(
        base_url="https://example.test/",
        timeout=8.0,
        session=session,
    )

    result = client.get_gap_chart(
        (" acb ", "FPT", "acb"),
        time_frame=" one_day ",
        count_back=2,
        to_timestamp=1_789_787_719,
    )

    assert result == {"t": [1, 2], "o": [25.0, 25.2]}
    assert session.post_calls == [
        (
            "https://example.test/api/chart/OHLCChart/gap-chart",
            {
                "json": {
                    "timeFrame": "ONE_DAY",
                    "symbols": ["ACB", "FPT"],
                    "countBack": 2,
                    "to": 1_789_787_719,
                },
                "headers": {"Accept": "application/json"},
                "timeout": 8.0,
            },
        )
    ]


@pytest.mark.parametrize("symbols", [(), [], "FPT"])
def test_get_gap_chart_rejects_invalid_symbol_collections(symbols: object) -> None:
    client = VietcapRestClient(session=FakeSession(FakeResponse({})))

    with pytest.raises((TypeError, ValueError)):
        client.get_gap_chart(
            symbols,  # type: ignore[arg-type]
            time_frame="ONE_DAY",
            count_back=2,
            to_timestamp=1,
        )


@pytest.mark.parametrize("time_frame", ["", "ONE-DAY", "ONE DAY"])
def test_get_gap_chart_rejects_invalid_time_frame(time_frame: str) -> None:
    client = VietcapRestClient(session=FakeSession(FakeResponse({})))

    with pytest.raises(ValueError, match="time_frame"):
        client.get_gap_chart(
            ("ACB",),
            time_frame=time_frame,
            count_back=2,
            to_timestamp=1,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("count_back", 0, ValueError),
        ("count_back", True, TypeError),
        ("to_timestamp", -1, ValueError),
        ("to_timestamp", 1.5, TypeError),
    ],
)
def test_get_gap_chart_rejects_invalid_integer_fields(
    field: str,
    value: object,
    error: type[Exception],
) -> None:
    kwargs: dict[str, object] = {"count_back": 2, "to_timestamp": 1}
    kwargs[field] = value
    client = VietcapRestClient(session=FakeSession(FakeResponse({})))

    with pytest.raises(error):
        client.get_gap_chart(
            ("ACB",),
            time_frame="ONE_DAY",
            **kwargs,  # type: ignore[arg-type]
        )


def test_get_gap_chart_wraps_http_errors() -> None:
    response = FakeResponse(request_error=requests.HTTPError("HTTP 503"))
    client = VietcapRestClient(session=FakeSession(response))

    with pytest.raises(VietcapRestError, match="Failed to fetch Vietcap gap chart"):
        client.get_gap_chart(
            ("ACB",),
            time_frame="ONE_DAY",
            count_back=2,
            to_timestamp=1,
        )


def test_get_gap_chart_wraps_invalid_json() -> None:
    response = FakeResponse(
        json_error=requests.exceptions.JSONDecodeError("invalid JSON", "x", 0)
    )
    client = VietcapRestClient(session=FakeSession(response))

    with pytest.raises(VietcapRestError, match="Invalid Vietcap gap-chart JSON"):
        client.get_gap_chart(
            ("ACB",),
            time_frame="ONE_DAY",
            count_back=2,
            to_timestamp=1,
        )


@pytest.mark.parametrize("payload", [None, [], "not-an-object"])
def test_get_gap_chart_rejects_non_object_json(payload: object) -> None:
    client = VietcapRestClient(session=FakeSession(FakeResponse(payload)))

    with pytest.raises(VietcapRestError, match="Invalid Vietcap gap-chart response"):
        client.get_gap_chart(
            ("ACB",),
            time_frame="ONE_DAY",
            count_back=2,
            to_timestamp=1,
        )

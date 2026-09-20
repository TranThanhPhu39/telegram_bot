"""Offline contract tests for Vietcap ICB2 membership snapshots."""

from datetime import date

import requests
import pytest

from asmf_data.vietcap_sectors import VietcapSectorClient, VietcapSectorError


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session(requests.Session):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def client(payload):
    return VietcapSectorClient(
        authorization="Bearer test", device_id="device", cookie="session=test",
        session=Session(payload),
    )


def test_snapshot_normalizes_real_contract_shape_and_filters_nonstocks() -> None:
    payload = [
        {"symbol": "acb", "type": "STOCK", "board": "HSX", "icbCode2": "8300"},
        {"symbol": "fpt", "type": "STOCK", "board": "HOSE", "icbCode2": 9500},
        {"symbol": "VN30", "type": "INDEX", "board": "HOSE", "icbCode2": None},
        {"symbol": "AAA", "type": "STOCK", "board": "OTC", "icbCode2": "1000"},
    ]
    rows = client(payload).snapshot(date(2026, 9, 20), industry_names={"8300": "Banks"})
    assert [(row.symbol, row.sector_code, row.sector_name) for row in rows] == [
        ("ACB", "8300", "Banks"), ("FPT", "9500", "ICB2 9500"),
    ]
    assert all(row.effective_from == date(2026, 9, 20) for row in rows)
    assert all(row.source == "Vietcap getAll ICB2 snapshot 2026-09-20" for row in rows)


def test_snapshot_rejects_conflicting_symbol_classification() -> None:
    payload = [
        {"symbol": "ACB", "type": "STOCK", "board": "HOSE", "icbCode2": "8300"},
        {"symbol": "ACB", "type": "STOCK", "board": "HNX", "icbCode2": "8500"},
    ]
    with pytest.raises(VietcapSectorError, match="conflicting"):
        client(payload).snapshot(date(2026, 9, 20))


def test_snapshot_rejects_empty_usable_result() -> None:
    with pytest.raises(VietcapSectorError, match="no usable"):
        client([]).snapshot(date(2026, 9, 20))

"""Regression test for Issue 9 follow-up bug:

TCBS 404/400 (ticker has no statement of this type) must be treated as
MISSING and must NOT be retried or counted toward the FINANCIALS circuit
breaker. Only genuine transport errors (timeout/connection/5xx) should be
retryable ERROR.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import requests

from fundamentals.providers.tcbs_provider import TCBSProvider


def _response(status: int, payload=None):
    resp = MagicMock()
    resp.status_code = status
    if status >= 400:
        def _raise():
            raise requests.HTTPError(f"{status} error")
        resp.raise_for_status = _raise
    else:
        resp.raise_for_status = lambda: None
    resp.json.return_value = payload if payload is not None else []
    return resp


def test_all_404_is_missing_not_failed():
    class Session:
        def get(self, url, params=None, timeout=None):
            return _response(404)

    result = TCBSProvider(session=Session()).fetch_financials("CH5")
    assert result.status.value == "MISSING"


def test_all_timeout_is_error_and_retryable():
    class Session:
        def get(self, url, params=None, timeout=None):
            raise TimeoutError("timed out")

    result = TCBSProvider(session=Session()).fetch_financials("CHX")
    assert result.status.value == "ERROR"


def test_partial_404_with_usable_data_is_not_failed():
    class Session:
        def get(self, url, params=None, timeout=None):
            if "balancesheet" in url:
                return _response(200, [{
                    "year": 2026, "quarter": 2,
                    "cash": 100, "asset": 500, "equity": 200, "debt": 300,
                }])
            return _response(404)

    result = TCBSProvider(session=Session()).fetch_financials("FPT")
    assert result.status.value in ("AVAILABLE", "PARTIAL")
    assert len(result.statements) == 1

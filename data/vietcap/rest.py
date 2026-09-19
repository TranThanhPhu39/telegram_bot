"""HTTP acquisition for the unofficial Vietcap market-data REST interface."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from enum import StrEnum
from typing import Any, Protocol
import logging
import re

import requests

from data.vietcap.constants import (
    DEFAULT_REST_BASE_URL,
    DEFAULT_REST_TIMEOUT_SECONDS,
    GAP_CHART_PATH,
    QUOTE_PATH_TEMPLATE,
)

logger = logging.getLogger(__name__)

_STOCK_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+\Z")
_OBSERVED_BROWSER_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5",
    "Content-Type": "application/json",
    "Priority": "u=1, i",
    "Sec-CH-UA": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
}


class VietcapRestError(RuntimeError):
    """Raised when Vietcap REST data cannot be acquired safely."""


class VietcapTimeFrame(StrEnum):
    """Observed timeframe identifiers accepted by the gap-chart contract."""

    ONE_MINUTE = "ONE_MINUTE"
    ONE_HOUR = "ONE_HOUR"
    ONE_DAY = "ONE_DAY"


class _HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class _HttpSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> _HttpResponse: ...

    def post(self, url: str, **kwargs: Any) -> _HttpResponse: ...


def normalize_stock_symbol(symbol: str) -> str:
    """Normalize and validate one stock ticker for safe URL construction."""
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not normalized or _STOCK_SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("symbol must contain only ASCII letters and digits")
    return normalized


def _normalize_stock_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    if isinstance(symbols, str):
        raise TypeError("symbols must be an iterable of ticker strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        ticker = normalize_stock_symbol(symbol)
        if ticker not in seen:
            normalized.append(ticker)
            seen.add(ticker)
    if not normalized:
        raise ValueError("at least one symbol is required")
    return tuple(normalized)


def normalize_time_frame(time_frame: VietcapTimeFrame | str) -> VietcapTimeFrame:
    """Normalize one supported provider timeframe or reject it before I/O."""
    if isinstance(time_frame, VietcapTimeFrame):
        return time_frame
    if not isinstance(time_frame, str):
        raise TypeError("time_frame must be a string")
    normalized = time_frame.strip().upper()
    try:
        return VietcapTimeFrame(normalized)
    except ValueError as exc:
        supported = ", ".join(timeframe.value for timeframe in VietcapTimeFrame)
        raise ValueError(f"Unsupported time_frame; expected one of: {supported}") from exc


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


class VietcapRestClient:
    """Fetch unnormalized Vietcap REST responses with bounded network calls."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_REST_BASE_URL,
        timeout: float = DEFAULT_REST_TIMEOUT_SECONDS,
        session: _HttpSession | None = None,
        authorization: str | None = None,
        device_id: str | None = None,
        cookie: str | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._base_url = normalized_base_url
        self._timeout = timeout
        self._session = session or requests.Session()
        self._authorization = self._optional_secret(authorization, "authorization")
        self._device_id = self._optional_secret(device_id, "device_id")
        self._cookie = self._optional_secret(cookie, "cookie")

    @staticmethod
    def _optional_secret(value: str | None, name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return normalized

    def _headers(self) -> dict[str, str]:
        headers = {
            **_OBSERVED_BROWSER_HEADERS,
            "Origin": self._base_url,
            "Referer": (
                f"{self._base_url}/priceboard?type=stock"
                "&filter-group=HOSE&filter-value=HOSE"
            ),
        }
        if self._authorization is not None:
            headers["Authorization"] = self._authorization
        if self._device_id is not None:
            headers["device-id"] = self._device_id
        if self._cookie is not None:
            headers["Cookie"] = self._cookie
        return headers

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Return one provider-native quote JSON object."""
        normalized_symbol = normalize_stock_symbol(symbol)
        path = QUOTE_PATH_TEMPLATE.format(symbol=normalized_symbol)
        url = f"{self._base_url}{path}"
        logger.info(
            "Fetching Vietcap quote",
            extra={"symbol": normalized_symbol, "url": url},
        )
        try:
            response = self._session.get(
                url,
                headers=self._headers(),
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except ValueError as exc:
            logger.exception(
                "Vietcap quote response was not valid JSON",
                extra={"symbol": normalized_symbol, "url": url},
            )
            raise VietcapRestError(
                f"Invalid Vietcap quote JSON for {normalized_symbol}"
            ) from exc
        except requests.RequestException as exc:
            logger.exception(
                "Vietcap quote request failed",
                extra={"symbol": normalized_symbol, "url": url},
            )
            raise VietcapRestError(
                f"Failed to fetch Vietcap quote for {normalized_symbol}"
            ) from exc

        if not isinstance(payload, Mapping):
            logger.error(
                "Vietcap quote response must be a JSON object",
                extra={
                    "symbol": normalized_symbol,
                    "url": url,
                    "payload_type": type(payload).__name__,
                },
            )
            raise VietcapRestError(
                f"Invalid Vietcap quote response for {normalized_symbol}"
            )
        return dict(payload)

    def get_gap_chart(
        self,
        symbols: Iterable[str],
        *,
        time_frame: VietcapTimeFrame | str,
        count_back: int,
        to_timestamp: int,
    ) -> list[dict[str, Any]]:
        """Return detached provider-native OHLC gap-chart rows."""
        normalized_symbols = _normalize_stock_symbols(symbols)
        normalized_time_frame = normalize_time_frame(time_frame)
        normalized_count_back = _positive_integer(count_back, "count_back")
        normalized_to = _positive_integer(to_timestamp, "to_timestamp")
        url = f"{self._base_url}{GAP_CHART_PATH}"
        request_body = {
            "timeFrame": normalized_time_frame.value,
            "symbols": list(normalized_symbols),
            "countBack": normalized_count_back,
            "to": normalized_to,
        }
        logger.info(
            "Fetching Vietcap OHLC gap chart",
            extra={
                "symbols": list(normalized_symbols),
                "time_frame": normalized_time_frame.value,
                "count_back": normalized_count_back,
                "to_timestamp": normalized_to,
                "url": url,
            },
        )
        try:
            response = self._session.post(
                url,
                json=request_body,
                headers=self._headers(),
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except ValueError as exc:
            logger.exception(
                "Vietcap gap-chart response was not valid JSON",
                extra={"url": url},
            )
            raise VietcapRestError("Invalid Vietcap gap-chart JSON") from exc
        except requests.RequestException as exc:
            logger.exception(
                "Vietcap gap-chart request failed",
                extra={"url": url},
            )
            raise VietcapRestError("Failed to fetch Vietcap gap chart") from exc

        if not isinstance(payload, list) or not all(
            isinstance(row, Mapping) for row in payload
        ):
            logger.error(
                "Vietcap gap-chart response must be an array of JSON objects",
                extra={"url": url, "payload_type": type(payload).__name__},
            )
            raise VietcapRestError("Invalid Vietcap gap-chart response")
        return deepcopy([dict(row) for row in payload])

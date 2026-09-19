"""HTTP acquisition for the unofficial Vietcap market-data REST interface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
import logging
import re

import requests

from data.vietcap.constants import (
    DEFAULT_REST_BASE_URL,
    DEFAULT_REST_TIMEOUT_SECONDS,
    QUOTE_PATH_TEMPLATE,
)

logger = logging.getLogger(__name__)

_STOCK_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]+\Z")


class VietcapRestError(RuntimeError):
    """Raised when Vietcap REST data cannot be acquired safely."""


class _HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class _HttpSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> _HttpResponse: ...


def normalize_stock_symbol(symbol: str) -> str:
    """Normalize and validate one stock ticker for safe URL construction."""
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not normalized or _STOCK_SYMBOL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("symbol must contain only ASCII letters and digits")
    return normalized


class VietcapRestClient:
    """Fetch unnormalized Vietcap REST responses with bounded network calls."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_REST_BASE_URL,
        timeout: float = DEFAULT_REST_TIMEOUT_SECONDS,
        session: _HttpSession | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._base_url = normalized_base_url
        self._timeout = timeout
        self._session = session or requests.Session()

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
                headers={"Accept": "application/json"},
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

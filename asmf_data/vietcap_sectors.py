"""Point-in-time ICB2 sector snapshot from the observed Vietcap catalog."""

from __future__ import annotations

from datetime import date
import logging
from typing import Mapping

import requests

from asmf_data.models import SectorMembership


LOGGER = logging.getLogger(__name__)
CATALOG_URL = "https://trading.vietcap.com.vn/api/price/symbols/getAll"
# The observed Vietcap catalog uses HSX for HOSE-listed instruments.
STOCK_EXCHANGES = {"HSX", "HOSE", "HNX", "UPCOM"}


class VietcapSectorError(RuntimeError):
    """Raised when the unofficial catalog cannot form a safe sector snapshot."""


class VietcapSectorClient:
    def __init__(
        self,
        *,
        authorization: str,
        device_id: str,
        cookie: str,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not all(value.strip() for value in (authorization, device_id, cookie)):
            raise ValueError("Vietcap authorization, device ID, and cookie are required")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "Accept": "application/json",
            "Authorization": authorization.strip(),
            "device-id": device_id.strip(),
            "Cookie": cookie.strip(),
            "Origin": "https://trading.vietcap.com.vn",
            "Referer": "https://trading.vietcap.com.vn/priceboard?type=stock",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def snapshot(
        self,
        observed_on: date,
        *,
        industry_names: Mapping[str, str] | None = None,
    ) -> tuple[SectorMembership, ...]:
        try:
            response = self.session.get(CATALOG_URL, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise VietcapSectorError(f"Vietcap catalog request failed: {exc}") from exc
        if not isinstance(payload, list):
            raise VietcapSectorError("Vietcap catalog response must be a JSON list")
        names = {str(code).strip().upper(): name.strip()
                 for code, name in (industry_names or {}).items() if name.strip()}
        by_symbol: dict[str, SectorMembership] = {}
        source = f"Vietcap getAll ICB2 snapshot {observed_on.isoformat()}"
        for item in payload:
            if not isinstance(item, dict):
                raise VietcapSectorError("Vietcap catalog row must be an object")
            if str(item.get("type", "")).upper() != "STOCK":
                continue
            exchange = str(item.get("board", "")).upper()
            if exchange not in STOCK_EXCHANGES:
                continue
            symbol = str(item.get("symbol", "")).strip().upper()
            code = str(item.get("icbCode2") or "").strip().upper()
            if not symbol or not symbol.isalnum() or not code or not code.isalnum():
                continue
            row = SectorMembership(
                symbol, code, names.get(code, f"ICB2 {code}"),
                observed_on, None, source,
            )
            existing = by_symbol.get(symbol)
            if existing is not None and existing.sector_code != code:
                raise VietcapSectorError(f"conflicting ICB2 codes for {symbol}")
            by_symbol[symbol] = row
        if not by_symbol:
            raise VietcapSectorError("Vietcap catalog contained no usable stock sectors")
        result = tuple(by_symbol[symbol] for symbol in sorted(by_symbol))
        LOGGER.info("Normalized %d Vietcap ICB2 memberships", len(result))
        return result

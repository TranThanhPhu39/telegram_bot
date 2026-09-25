"""Ordered provider chain with honest provenance.

The chain stops at the first usable result. A provider that answers AVAILABLE
or PARTIAL ends the chain, so the fallback is never called when the primary
source succeeded — which is both a correctness property (provenance must name
the source that actually answered) and a rate-limit property.

MISSING and ERROR both justify trying the next provider, but they are kept
distinct in the audit trail so operators can tell "Yahoo has no such ticker"
apart from "Yahoo timed out".
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import logging

from fundamentals.providers.base import (
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
)

LOGGER = logging.getLogger(__name__)


class ProviderChain:
    """Try providers in order; return the first usable result."""

    def __init__(self, providers: Sequence[FundamentalProvider]) -> None:
        if not providers:
            raise ValueError("a provider chain needs at least one provider")
        self._providers = tuple(providers)

    @property
    def providers(self) -> tuple[FundamentalProvider, ...]:
        return self._providers

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        return self._run("FINANCIALS", symbol, exchange=exchange)

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        return self._run(
            "INSTITUTIONAL", symbol, exchange=exchange, lookback_days=lookback_days,
        )

    def _run(
        self, dataset: str, symbol: str, *, exchange: str | None,
        lookback_days: int = 30,
    ) -> ProviderResult:
        symbol = symbol.strip().upper()
        attempted: list[str] = []
        first_error: ProviderResult | None = None

        for provider in self._providers:
            try:
                if dataset == "FINANCIALS":
                    result = provider.fetch_financials(symbol, exchange=exchange)
                else:
                    result = provider.fetch_institutional_flow(
                        symbol, exchange=exchange, lookback_days=lookback_days,
                    )
            except Exception as error:  # an adapter must not break the chain
                LOGGER.warning(
                    "provider %s raised for %s/%s: %s",
                    provider.name, symbol, dataset, type(error).__name__,
                )
                result = ProviderResult.failed(
                    symbol, dataset, provider.name,
                    f"{type(error).__name__} escaped the adapter",
                )
            attempted.append(f"{provider.name}:{result.status.value}")
            if result.status.usable:
                return ProviderResult(
                    symbol=result.symbol, dataset=result.dataset,
                    provider=result.provider, status=result.status,
                    provider_source=result.provider_source,
                    retrieved_at=result.retrieved_at or datetime.now(timezone.utc),
                    statements=result.statements, flows=result.flows,
                    error_reason=result.error_reason, attempted=tuple(attempted),
                    diagnostic_code=result.diagnostic_code,
                    statement_schema=result.statement_schema,
                )
            if result.status is ProviderStatus.ERROR and first_error is None:
                first_error = result

        if first_error is not None:
            return ProviderResult(
                symbol=symbol, dataset=dataset, provider=first_error.provider,
                status=ProviderStatus.ERROR,
                provider_source=first_error.provider_source,
                retrieved_at=datetime.now(timezone.utc),
                error_reason=first_error.error_reason,
                attempted=tuple(attempted),
                diagnostic_code=first_error.diagnostic_code,
                statement_schema=first_error.statement_schema,
            )
        # Issue 4: attributing this to `self._providers[-1].name` (e.g.
        # "yfinance") falsely implied that provider was relied upon/valid for
        # this dataset -- live evidence showed
        # "provider=yfinance reason=no provider in the chain had data" for
        # institutional flow, which reads as "we used yfinance and it had
        # nothing" when in fact *no* provider in the chain (including the
        # authoritative VNStock/Vietcap one) had usable data, and yfinance
        # itself never claims to carry Vietnamese institutional flow at all
        # (see YFinanceProvider.fetch_institutional_flow). "none" makes that
        # honest, and the reason lists every provider actually attempted.
        return ProviderResult(
            symbol=symbol, dataset=dataset,
            provider="none", status=ProviderStatus.MISSING,
            retrieved_at=datetime.now(timezone.utc),
            error_reason="no provider had data (attempted: " + ", ".join(attempted) + ")",
            attempted=tuple(attempted),
        )


def build_default_chain(
    *,
    vietcap_iq_session: object | None = None,
    vietcap_iq_enabled: bool = False,
    vietcap_authorization: str | None = None,
    vnstock_module: object | None = None,
    yfinance_module: object | None = None,
    tcbs_session: object | None = None,
    source_preference: Sequence[str] | None = None,
    yfinance_enabled: bool = True,
    tcbs_enabled: bool = True,
) -> ProviderChain:
    """Vietcap IQ first when enabled, then VNStock, TCBS and Yahoo.

    TCBS sits ahead of yfinance because it is a Vietnamese-market-specific
    source (see ``tcbs_provider.py``), so it is a closer analog to VNStock
    than the Yahoo fallback is; it is still tried after VNStock so a healthy
    primary source is never skipped.
    """
    from fundamentals.providers.tcbs_provider import TCBSProvider
    from fundamentals.providers.vietcap_iq_provider import VietcapIQFinancialProvider
    from fundamentals.providers.vnstock_provider import (
        DEFAULT_SOURCE_PREFERENCE, VNStockProvider,
    )
    from fundamentals.providers.yfinance_provider import YFinanceProvider

    providers: list[FundamentalProvider] = []
    if vietcap_iq_enabled:
        providers.append(VietcapIQFinancialProvider(
            session=vietcap_iq_session,
            enabled=True,
            authorization=vietcap_authorization,
        ))
    providers.extend((
        VNStockProvider(
            module=vnstock_module,
            source_preference=source_preference or DEFAULT_SOURCE_PREFERENCE,
        ),
        TCBSProvider(session=tcbs_session, enabled=tcbs_enabled),
        YFinanceProvider(module=yfinance_module, enabled=yfinance_enabled),
    ))
    return ProviderChain(providers)

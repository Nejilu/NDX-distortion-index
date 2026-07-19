"""Snapshot orchestration independent from the API and dashboard surfaces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database import SnapshotDatabase
from distortion_engine import DistortionResult, calculate_distortion
from market_data_provider import CsvMarketDataProvider, YFinanceMarketDataProvider
from qqq_holdings_provider import (
    DEFAULT_CNDX_URL,
    DEFAULT_EQQQ_URL,
    DEFAULT_IQQ_URL,
    CsvHoldingsProvider,
    HoldingsProviderChain,
    HttpCsvHoldingsProvider,
    InvescoQQQHoldingsProvider,
    IsharesSpreadsheetXmlHoldingsProvider,
)


ROOT = Path(__file__).resolve().parent
SAMPLE_NON_UCITS_HOLDINGS = ROOT / "data" / "sample_qqq_holdings.csv"
SAMPLE_UCITS_HOLDINGS = ROOT / "data" / "sample_ucits_holdings.csv"
SAMPLE_MARKET_DATA = ROOT / "data" / "sample_market_data.csv"
UNIVERSES = ("non_ucits", "ucits")


@dataclass(frozen=True)
class RecomputeOutcome:
    snapshot_id: int
    timestamp: str
    result: DistortionResult
    holdings_source: str
    market_data_source: str
    universe: str = "non_ucits"
    reference_fund: str | None = None
    holdings_as_of: str | None = None
    source_failures: tuple[str, ...] = ()
    fallback_reason: str | None = None

    def summary(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "ndx_wdi": self.result.ndx_wdi,
            "coverage_ratio": self.result.coverage_ratio,
            "constituent_count": self.result.constituent_count,
            "missing_float_count": self.result.missing_float_count,
            "invalid_float_count": self.result.invalid_float_count,
            "missing_reference_shares_count": self.result.missing_reference_shares_count,
            "missing_price_count": self.result.missing_price_count,
            "snapshot_status": self.result.snapshot_status,
            "weighting_basis": self.result.weighting_basis,
            "universe": self.universe,
            "reference_fund": self.reference_fund,
            "holdings_as_of": self.holdings_as_of,
            "holdings_source": self.holdings_source,
            "market_data_source": self.market_data_source,
            "source_failures": list(self.source_failures),
            "fallback_reason": self.fallback_reason,
        }


def recompute_snapshot(
    *,
    mode: str | None = None,
    db_path: str | Path | None = None,
    holdings_csv: str | Path | None = None,
    universe: str = "non_ucits",
    weighting_basis: str = "float",
) -> RecomputeOutcome:
    """Compute and persist one snapshot in live, sample or automatic mode."""
    selected_mode = (mode or os.getenv("NDX_DATA_MODE", "auto")).lower()
    if selected_mode not in {"auto", "live", "sample"}:
        raise ValueError("NDX_DATA_MODE doit valoir auto, live ou sample.")
    if universe not in UNIVERSES:
        raise ValueError(f"universe doit valoir l'une de ces valeurs: {UNIVERSES}.")
    if weighting_basis not in {"float", "total"}:
        raise ValueError("weighting_basis doit valoir float ou total.")
    database = SnapshotDatabase(db_path or os.getenv("NDX_DB_PATH", "data/ndx_wdi.sqlite3"))
    coverage_threshold = float(os.getenv("NDX_COVERAGE_THRESHOLD", "0.99"))

    fallback_reason: str | None = None
    source_failures: tuple[str, ...] = ()
    holdings_as_of: str | None = None
    if selected_mode == "sample":
        result, holdings_source, market_source, reference_fund = _compute_sample(
            coverage_threshold, universe, weighting_basis
        )
    else:
        try:
            holdings_provider = build_holdings_chain(universe, holdings_csv=holdings_csv)
            market_provider = YFinanceMarketDataProvider(
                max_workers=int(os.getenv("YFINANCE_MAX_WORKERS", "8")),
                cache_dir=os.getenv("YFINANCE_CACHE_DIR", "data/yfinance_cache"),
            )
            holdings = holdings_provider.get_holdings()
            source_failures = holdings_provider.failures
            holdings_as_of = holdings_provider.holdings_as_of
            market_data = market_provider.get_market_data(holdings["ticker"].tolist())
            result = calculate_distortion(
                holdings,
                market_data,
                coverage_threshold=coverage_threshold,
                source_status="live",
                weighting_basis=weighting_basis,
            )
            holdings_source = holdings_provider.source_name
            reference_fund = holdings_provider.reference_fund
            market_source = market_provider.source_name
        except Exception as exc:
            if selected_mode == "live":
                raise
            fallback_reason = f"{type(exc).__name__}: {exc}"
            if "holdings_provider" in locals():
                source_failures = holdings_provider.failures
            result, holdings_source, market_source, reference_fund = _compute_sample(
                coverage_threshold, universe, weighting_basis
            )

    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot_id = database.save_snapshot(
        result,
        timestamp=timestamp,
        universe=universe,
        reference_fund=reference_fund,
        holdings_as_of=holdings_as_of,
        source_failures=" | ".join(source_failures) or None,
        holdings_source=holdings_source,
        market_data_source=market_source,
        weighting_basis=weighting_basis,
    )
    return RecomputeOutcome(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        result=result,
        holdings_source=holdings_source,
        market_data_source=market_source,
        universe=universe,
        reference_fund=reference_fund,
        holdings_as_of=holdings_as_of,
        source_failures=source_failures,
        fallback_reason=fallback_reason,
    )


def recompute_all_snapshots(
    *,
    mode: str | None = None,
    db_path: str | Path | None = None,
    weighting_basis: str = "float",
) -> list[RecomputeOutcome]:
    return [
        recompute_snapshot(
            mode=mode,
            db_path=db_path,
            universe=universe,
            weighting_basis=weighting_basis,
        )
        for universe in UNIVERSES
    ]


def build_holdings_chain(
    universe: str, *, holdings_csv: str | Path | None = None
) -> HoldingsProviderChain:
    timeout = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
    providers = []
    configured_csv = holdings_csv or os.getenv(
        "NON_UCITS_HOLDINGS_CSV" if universe == "non_ucits" else "UCITS_HOLDINGS_CSV"
    )
    if universe == "non_ucits" and not configured_csv:
        configured_csv = os.getenv("QQQ_HOLDINGS_CSV")
    if configured_csv:
        providers.append(
            CsvHoldingsProvider(
                configured_csv,
                source_name=f"configured_{universe}_csv",
                reference_fund="configured_csv",
            )
        )

    if universe == "non_ucits":
        providers.extend(
            [
                IsharesSpreadsheetXmlHoldingsProvider(
                    url=os.getenv("IQQ_HOLDINGS_URL", DEFAULT_IQQ_URL), timeout=timeout
                ),
                InvescoQQQHoldingsProvider(
                    url=os.getenv("QQQ_HOLDINGS_URL", InvescoQQQHoldingsProvider.url),
                    timeout=timeout,
                ),
            ]
        )
        extra_urls = os.getenv("NON_UCITS_FALLBACK_URLS", "")
    else:
        providers.extend(
            [
                HttpCsvHoldingsProvider(
                    url=os.getenv("CNDX_HOLDINGS_URL", DEFAULT_CNDX_URL),
                    source_name="ishares_cndx_public_holdings",
                    reference_fund="CNDX",
                    timeout=timeout,
                ),
                HttpCsvHoldingsProvider(
                    url=os.getenv("EQQQ_HOLDINGS_URL", DEFAULT_EQQQ_URL),
                    source_name="invesco_eqqq_public_holdings",
                    reference_fund="EQQQ",
                    timeout=timeout,
                ),
            ]
        )
        extra_urls = os.getenv("UCITS_FALLBACK_URLS", "")

    for index, url in enumerate(filter(None, (item.strip() for item in extra_urls.split(","))), 1):
        providers.append(
            HttpCsvHoldingsProvider(
                url=url,
                source_name=f"configured_{universe}_url_{index}",
                reference_fund="configured_url",
                timeout=timeout,
            )
        )
    return HoldingsProviderChain(providers)


def _compute_sample(
    coverage_threshold: float, universe: str, weighting_basis: str
) -> tuple[DistortionResult, str, str, str]:
    path = SAMPLE_NON_UCITS_HOLDINGS if universe == "non_ucits" else SAMPLE_UCITS_HOLDINGS
    reference_fund = "SAMPLE_QQQ" if universe == "non_ucits" else "SAMPLE_CNDX"
    holdings_provider = CsvHoldingsProvider(
        path, source_name=f"sample_{universe}_holdings", reference_fund=reference_fund
    )
    market_provider = CsvMarketDataProvider(SAMPLE_MARKET_DATA)
    holdings = holdings_provider.get_holdings()
    market_data = market_provider.get_market_data(holdings["ticker"].tolist())
    result = calculate_distortion(
        holdings,
        market_data,
        coverage_threshold=coverage_threshold,
        source_status="sample_fallback",
        weighting_basis=weighting_basis,
    )
    return result, holdings_provider.source_name, market_provider.source_name, reference_fund

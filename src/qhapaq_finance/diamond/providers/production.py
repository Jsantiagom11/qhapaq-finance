"""Production provider composition shared by Diamond and Executive."""

from __future__ import annotations

from pathlib import Path

from qhapaq_finance.sec_client import SecClient
from qhapaq_finance.sec_config import SecConfig

from ..cache import DiamondCache
from .sec import SecFirstProvider, SecFirstProviderError
from .sec_canonical import CanonicalIssuerCache
from .sec_evidence import SecEvidenceStore
from .sp500 import Sp500UniverseProvider, WikipediaTextClient
from .yahoo import YahooBatchMarketProvider, YahooClient
from .yahoo_splits import YahooSplitAdjustmentProvider


def build_funnel_provider(
    cache_root: Path,
    *,
    refresh: bool,
    offline: bool = False,
) -> SecFirstProvider:
    """Compose the SEC-first provider and its local evidence stores."""
    if offline and refresh:
        raise SecFirstProviderError("OFFLINE_REFRESH_CONFLICT")

    sec_client: SecClient | None = None
    if not offline:
        try:
            sec_config = SecConfig.from_env()
        except RuntimeError as exc:
            raise SecFirstProviderError(f"SEC_CONFIG_INVALID:{exc}") from exc
        sec_client = SecClient(sec_config)

    universe_provider = Sp500UniverseProvider(
        client=None if offline else WikipediaTextClient(),
        cache=DiamondCache(cache_root / "universe"),
        refresh=refresh,
    )
    evidence_store = SecEvidenceStore(
        root=cache_root / "sec",
        client=sec_client,
        legacy_cache=DiamondCache(cache_root / "sec"),
        offline=offline,
    )
    canonical_cache = CanonicalIssuerCache(DiamondCache(cache_root / "canonical"))
    market_provider = YahooBatchMarketProvider(
        client=None if offline else YahooClient(),
        cache=DiamondCache(cache_root / "market"),
        refresh=refresh,
    )
    split_provider = YahooSplitAdjustmentProvider(
        client=None if offline else YahooClient(),
        cache=DiamondCache(cache_root / "splits"),
        refresh=refresh,
    )

    return SecFirstProvider(
        universe_provider=universe_provider,
        evidence_store=evidence_store,
        canonical_cache=canonical_cache,
        market_provider=market_provider,
        split_provider=split_provider,
        refresh=refresh,
        offline=offline,
    )

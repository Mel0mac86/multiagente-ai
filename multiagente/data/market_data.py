"""MarketDataAgent + adapter dei feed con failover (ARCHITETTURA.md §5.1).

Normalizza i dati da feed multipli, rileva i dati stantii e fa failover sul
secondario marcando lo snapshot come degradato.
"""

from __future__ import annotations

import abc
import logging
import time

from ..config import FaultConfig
from ..core.types import MarketSnapshot

logger = logging.getLogger(__name__)


class FeedAdapter(abc.ABC):
    """Adapter astratto di un feed di mercato. Implementa il provider concreto qui."""

    name: str

    @abc.abstractmethod
    def fetch(self, symbol: str) -> MarketSnapshot:
        """Restituisce lo snapshot grezzo per lo strumento (alza eccezione se giù)."""


class StubFeed(FeedAdapter):
    """Feed di esempio per la demo: genera uno snapshot deterministico-ish.

    In produzione si sostituisce con un adapter REST/WebSocket reale.
    """

    def __init__(self, name: str, base_prices: dict[str, float]) -> None:
        self.name = name
        self._base = base_prices
        self._t = 0

    def fetch(self, symbol: str) -> MarketSnapshot:
        if symbol not in self._base:
            raise KeyError(f"{self.name}: simbolo sconosciuto {symbol}")
        self._t += 1
        base = self._base[symbol]
        # piccola oscillazione pseudo-casuale ma riproducibile
        drift = ((hash((symbol, self._t)) % 1000) / 1000.0 - 0.5) * base * 0.002
        mid = base + drift
        spread = mid * 0.0001  # ~1 bps
        return MarketSnapshot(
            symbol=symbol,
            ts=time.time(),
            bid=mid - spread / 2,
            ask=mid + spread / 2,
            last=mid,
            ohlcv={"1m": [mid] * 30},
            book_imbalance=((hash((symbol, self._t, "imb")) % 200) / 100.0 - 1.0),
        )


class MarketDataAgent:
    """Aggrega più feed con failover e rilevazione dati stantii."""

    def __init__(self, feeds: list[FeedAdapter], cfg: FaultConfig) -> None:
        if not feeds:
            raise ValueError("serve almeno un feed")
        self.feeds = feeds  # [primario, secondario, ...]
        self.cfg = cfg

    def snapshot(self, symbol: str) -> MarketSnapshot | None:
        """Snapshot normalizzato. ``None`` se nessun feed risponde."""
        for i, feed in enumerate(self.feeds):
            try:
                snap = feed.fetch(symbol)
            except Exception as exc:  # noqa: BLE001 - failover sul prossimo feed
                logger.warning("Feed %s giù su %s: %s", feed.name, symbol, exc)
                continue
            # rilevazione dati stantii
            if time.time() - snap.ts > self.cfg.stale_data_timeout_s:
                logger.warning("Dati stantii da %s su %s", feed.name, symbol)
                snap.degraded = True
            if i > 0:
                snap.degraded = True  # in uso un feed di backup
            return snap
        logger.error("Nessun feed disponibile per %s", symbol)
        return None

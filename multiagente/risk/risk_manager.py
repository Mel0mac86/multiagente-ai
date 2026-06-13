"""RiskManagerAgent — autorità finale prima dell'esecuzione (ARCHITETTURA.md §5.5).

Dimensiona la posizione (rischio per trade), applica limiti di esposizione per
cluster di correlazione e leva, rispetta le blackout window e può attivare il
kill switch al superamento del drawdown massimo.
"""

from __future__ import annotations

import logging
import time

from ..config import RiskConfig
from ..core.faults import KillSwitch
from ..core.types import Order, PairProfile, Side, ValidatedSignal

logger = logging.getLogger(__name__)


class RiskManagerAgent:
    def __init__(self, cfg: RiskConfig, capital: float, kill_switch: KillSwitch) -> None:
        self.cfg = cfg
        self.capital = capital
        self.kill = kill_switch
        # esposizione corrente per cluster (in multipli del capitale)
        self._cluster_exposure: dict[str, float] = {}
        self._exposure_by_symbol: dict[str, tuple[str, float]] = {}
        self._gross_exposure = 0.0
        self._day_start_equity = capital
        self._equity = capital

    # --- aggiornamento equity (chiamato dal Portfolio) --------------------- #
    def update_equity(self, equity: float) -> None:
        self._equity = equity
        dd = (self._day_start_equity - equity) / self._day_start_equity
        if dd >= self.cfg.max_daily_drawdown:
            self.kill.engage(f"drawdown giornaliero {dd:.1%} >= {self.cfg.max_daily_drawdown:.1%}")

    def start_new_day(self) -> None:
        self._day_start_equity = self._equity

    # --- valutazione di un segnale ---------------------------------------- #
    def assess(
        self, vsig: ValidatedSignal, profile: PairProfile
    ) -> Order | None:
        if self.kill.engaged:
            logger.warning("Kill switch attivo: ordine rifiutato")
            return None

        sig = vsig.signal

        # Blackout window (dalla sentiment, propagata via segnale/regime).
        # (qui semplificato: il router già esclude i desk in blackout)

        # Position sizing: rischio per trade / distanza dallo stop.
        risk_amount = self.capital * self.cfg.risk_per_trade
        stop_dist = abs(sig.entry - sig.stop)
        if stop_dist <= 0:
            return None
        quantity = risk_amount / stop_dist

        # Vincolo di leva del profilo.
        notional = quantity * sig.entry
        max_notional = self.capital * profile.leverage_cap
        if notional > max_notional:
            quantity = max_notional / sig.entry
            notional = max_notional

        # Limite di esposizione per cluster di correlazione.
        cluster = profile.correlation_cluster
        cluster_now = self._cluster_exposure.get(cluster, 0.0)
        add = notional / self.capital
        if cluster_now + add > self.cfg.max_cluster_exposure:
            logger.info("Limite cluster '%s' superato: ordine ridotto/rifiutato", cluster)
            allowed = max(0.0, self.cfg.max_cluster_exposure - cluster_now)
            if allowed <= 0:
                return None
            quantity = allowed * self.capital / sig.entry
            notional = quantity * sig.entry
            add = notional / self.capital

        # Limite di esposizione lorda totale.
        if self._gross_exposure + add > self.cfg.max_gross_exposure:
            logger.info("Limite esposizione lorda superato: ordine rifiutato")
            return None

        # Scalping → ordine limit per controllare lo slippage; altrimenti market.
        # L'esposizione viene registrata al fill (register_fill) e rilasciata alla
        # chiusura (release): così un ordine non eseguito non lascia esposizione fantasma.
        order_type = "limit" if sig.horizon.value == "scalping" else "market"
        # arrotonda al lotto solo se definito (lot_size>0); altrimenti quantità libera
        if profile.lot_size > 0:
            quantity = round(quantity / profile.lot_size) * profile.lot_size or profile.lot_size
        return Order(
            symbol=sig.symbol,
            side=sig.side,
            quantity=quantity,
            order_type=order_type,
            limit_price=sig.entry if order_type == "limit" else None,
            stop=sig.stop,
            target=sig.target,
            meta={
                "sources": vsig.sources,
                "confidence": vsig.aggregate_confidence,
                "cluster": cluster,
                "exposure_add": add,
                "ts": time.time(),
            },
        )

    # --- registrazione/rilascio dell'esposizione (chiamati dal Portfolio) --- #
    def register_fill(self, symbol: str, cluster: str, exposure_add: float) -> None:
        """Registra l'esposizione di una posizione effettivamente aperta."""
        self._cluster_exposure[cluster] = self._cluster_exposure.get(cluster, 0.0) + exposure_add
        self._gross_exposure += exposure_add
        self._exposure_by_symbol[symbol] = (cluster, exposure_add)

    def release(self, symbol: str) -> None:
        """Rilascia l'esposizione alla chiusura della posizione."""
        entry = self._exposure_by_symbol.pop(symbol, None)
        if entry is None:
            return
        cluster, add = entry
        self._cluster_exposure[cluster] = max(0.0, self._cluster_exposure.get(cluster, 0.0) - add)
        self._gross_exposure = max(0.0, self._gross_exposure - add)

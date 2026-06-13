"""Agente base + mixin di auto-adattamento (ARCHITETTURA.md §9).

Tutti gli agenti di strategia ereditano da ``StrategyAgent``. Il mixin di
adattamento mantiene metriche per regime e regola i parametri entro guardrail.
"""

from __future__ import annotations

import abc
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from .types import Horizon, Regime, Signal, TaskContext

logger = logging.getLogger(__name__)


@dataclass
class PerformanceStats:
    """Metriche di performance accumulate (per regime) — alimentate dal Portfolio."""

    trades: int = 0
    wins: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 1.0
        return self.gross_profit / abs(self.gross_loss)


class AdaptiveMixin:
    """Auto-adattamento: metriche per regime, peso di voto, quarantena.

    L'influenza di un agente nel consenso (ARCHITETTURA.md §8) segue il merito
    recente *per regime*. Sotto soglia → quarantena (shadow mode).
    """

    #: profit factor minimo per restare attivo (oltre una finestra minima di trade)
    QUARANTINE_PF_THRESHOLD: float = 1.0
    MIN_TRADES_FOR_QUARANTINE: int = 20

    def __init__(self) -> None:
        self._stats: dict[Regime, PerformanceStats] = defaultdict(PerformanceStats)
        self._quarantined = False
        # Parametri adattivi con guardrail: nome -> (valore, min, max).
        self._params: dict[str, tuple[float, float, float]] = {}

    # --- parametri adattivi ------------------------------------------------ #
    def register_param(self, name: str, value: float, lo: float, hi: float) -> None:
        self._params[name] = (value, lo, hi)

    def param(self, name: str) -> float:
        return self._params[name][0]

    def _nudge_param(self, name: str, factor: float) -> None:
        """Regola un parametro entro i guardrail (controllo a feedback)."""
        value, lo, hi = self._params[name]
        new_value = min(hi, max(lo, value * factor))
        if new_value != value:
            logger.info("Adatto %s: %.4f -> %.4f", name, value, new_value)
        self._params[name] = (new_value, lo, hi)

    # --- feedback dal PortfolioAgent --------------------------------------- #
    def record_outcome(self, regime: Regime, pnl: float) -> None:
        """Aggiorna le metriche e adatta i parametri/quarantena."""
        s = self._stats[regime]
        s.trades += 1
        if pnl >= 0:
            s.wins += 1
            s.gross_profit += pnl
        else:
            s.gross_loss += pnl
        self._evaluate_quarantine(regime)
        self._adapt(regime, pnl)

    def _adapt(self, regime: Regime, pnl: float) -> None:
        """Override negli agenti concreti per regolare le proprie soglie."""

    def _evaluate_quarantine(self, regime: Regime) -> None:
        s = self._stats[regime]
        if s.trades >= self.MIN_TRADES_FOR_QUARANTINE:
            should = s.profit_factor < self.QUARANTINE_PF_THRESHOLD
            if should and not self._quarantined:
                logger.warning("Quarantena attivata (PF=%.2f, regime=%s)", s.profit_factor, regime)
            self._quarantined = should

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    def vote_weight(self, regime: Regime) -> float:
        """Peso nel consenso: 0 se in quarantena, altrimenti scala col profit factor."""
        if self._quarantined:
            return 0.0
        pf = self._stats[regime].profit_factor
        return min(2.0, max(0.1, pf))  # cap per evitare dominanza


class StrategyAgent(AdaptiveMixin, abc.ABC):
    """Base per gli agenti di strategia. Producono *proposte* (Signal), non ordini."""

    horizon: Horizon

    def __init__(self, name: str) -> None:
        AdaptiveMixin.__init__(self)
        self.name = name

    @abc.abstractmethod
    def evaluate(self, ctx: TaskContext) -> Signal | None:
        """Restituisce una proposta di segnale o None se non c'è edge."""

    def __repr__(self) -> str:  # pragma: no cover - utilità di debug
        return f"<{type(self).__name__} {self.name} horizon={self.horizon}>"

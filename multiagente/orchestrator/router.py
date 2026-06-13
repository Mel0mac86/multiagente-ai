"""Router — instrada le attività (ARCHITETTURA.md §6).

Per ogni strumento costruisce il TaskContext (snapshot, profilo, regime,
sentiment), applica i gate di ammissibilità per desk e raccoglie le proposte
degli agenti specializzati per il regime corrente.
"""

from __future__ import annotations

import logging

from ..core.agent import StrategyAgent
from ..core.messaging import Blackboard, MessageBus
from ..core.types import (
    Horizon,
    LiquidityTier,
    Regime,
    Signal,
    TaskContext,
)
from ..data.market_data import MarketDataAgent
from ..data.pair_classifier import PairClassifierAgent
from ..data.regime import RegimeDetectorAgent
from ..agents.sentiment import NewsSentimentAgent

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        market_data: MarketDataAgent,
        classifier: PairClassifierAgent,
        regime_detector: RegimeDetectorAgent,
        sentiment: NewsSentimentAgent,
        desks: dict[Horizon, list[StrategyAgent]],
        bus: MessageBus,
        blackboard: Blackboard,
    ) -> None:
        self.market_data = market_data
        self.classifier = classifier
        self.regime_detector = regime_detector
        self.sentiment = sentiment
        self.desks = desks
        self.bus = bus
        self.blackboard = blackboard

    def route(self, symbol: str) -> list[Signal]:
        """Produce le proposte di segnale per uno strumento."""
        snap = self.market_data.snapshot(symbol)
        if snap is None:
            return []  # nessun feed → sospendi

        profile = self.classifier.profile(symbol)
        if profile is None:
            logger.warning("Nessun profilo per %s: strumento scartato", symbol)
            return []

        sentiment = self.sentiment.assess(profile)
        regime = self.regime_detector.regime(snap, profile, sentiment)

        # Aggiorna la blackboard condivisa.
        self.blackboard.namespaced("regime", symbol, regime)
        self.blackboard.namespaced("sentiment", symbol, sentiment)

        ctx = TaskContext(snapshot=snap, profile=profile, regime=regime, sentiment=sentiment)
        self.bus.publish("task_context", ctx)

        signals: list[Signal] = []
        for horizon, agents in self.desks.items():
            if not self._desk_admissible(horizon, ctx):
                continue
            for agent in agents:
                try:
                    sig = agent.evaluate(ctx)
                except Exception as exc:  # noqa: BLE001 - un agente non blocca gli altri
                    logger.exception("Agente %s ha fallito su %s: %s", agent.name, symbol, exc)
                    continue
                if sig is not None:
                    signals.append(sig)
        if signals:
            self.bus.publish("signals", signals)
        return signals

    # --- gate di ammissibilità (ARCHITETTURA.md §6) ------------------------ #
    def _desk_admissible(self, horizon: Horizon, ctx: TaskContext) -> bool:
        regime = ctx.regime.regime
        profile = ctx.snapshot and ctx.profile

        # Blackout pre-evento: sospende scalping e day trading (ma non l'investor).
        blackout = ctx.sentiment is not None and ctx.sentiment.blackout_until is not None
        if blackout and horizon in (Horizon.SCALPING, Horizon.DAY_TRADING):
            return False

        if horizon is Horizon.SCALPING:
            # solo T1, niente regime news_driven, spread non proibitivo
            if profile.liquidity_tier != LiquidityTier.T1:
                return False
            if regime is Regime.NEWS_DRIVEN:
                return False
            return True

        if horizon is Horizon.DAY_TRADING:
            return regime is not Regime.NEWS_DRIVEN

        # Investor: sempre ammissibile (bassa frequenza, veto macro).
        return True

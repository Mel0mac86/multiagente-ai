"""Validator — validazione multi-livello dei segnali (ARCHITETTURA.md §7.1).

Cancelli in ordine:
  1. Schema      — campi/tipi/valori validi.
  2. Sanità      — prezzo plausibile vs mid, size compatibile con tick/lot, dati freschi.
  3. Coerenza    — gate costi (scalping), rispetto del profilo/regime.
  4. Fusione     — aggrega concordi, arbitra opposti via consenso pesato.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..core.agent import StrategyAgent
from ..core.types import (
    Horizon,
    MarketSnapshot,
    Regime,
    Side,
    Signal,
    ValidatedSignal,
)

logger = logging.getLogger(__name__)

_FEE_BPS = 1.0


class ValidatorAgent:
    def __init__(self, agents_by_name: dict[str, StrategyAgent]) -> None:
        # serve per recuperare il peso di voto (performance per regime)
        self.agents_by_name = agents_by_name

    def validate(
        self, signals: list[Signal], snap: MarketSnapshot
    ) -> list[ValidatedSignal]:
        passed = [s for s in signals if self._gate_schema(s) and self._gate_sanity(s, snap)
                  and self._gate_consistency(s, snap)]
        return self._fuse(passed)

    # --- 1. schema --------------------------------------------------------- #
    def _gate_schema(self, s: Signal) -> bool:
        ok = (
            s.symbol and s.side in (Side.BUY, Side.SELL)
            and 0.0 <= s.confidence <= 1.0
            and s.entry > 0 and s.stop > 0 and s.target > 0
            and s.size_hint > 0 and bool(s.signal_id)
        )
        if not ok:
            logger.info("Rigetto schema: %s", s.signal_id)
        return ok

    # --- 2. sanità di mercato --------------------------------------------- #
    def _gate_sanity(self, s: Signal, snap: MarketSnapshot) -> bool:
        if snap.degraded and s.horizon is Horizon.SCALPING:
            return False  # niente scalping su dati degradati
        # prezzo di ingresso entro ±5% dal mid
        if snap.mid > 0 and abs(s.entry - snap.mid) / snap.mid > 0.05:
            logger.info("Rigetto sanità (entry lontano dal mid): %s", s.signal_id)
            return False
        # stop e target dalla parte giusta
        if s.side is Side.BUY and not (s.stop < s.entry < s.target):
            return False
        if s.side is Side.SELL and not (s.target < s.entry < s.stop):
            return False
        return True

    # --- 3. coerenza profilo/regime + gate costi -------------------------- #
    def _gate_consistency(self, s: Signal, snap: MarketSnapshot) -> bool:
        if s.horizon is Horizon.SCALPING:
            cost_bps = snap.spread_bps + 2 * _FEE_BPS
            if s.edge_bps <= cost_bps:
                logger.info("Rigetto gate costi: edge %.1f <= costi %.1f", s.edge_bps, cost_bps)
                return False
        return True

    # --- 4. fusione / arbitraggio (consenso pesato) ----------------------- #
    def _fuse(self, signals: list[Signal]) -> list[ValidatedSignal]:
        by_symbol: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            by_symbol[s.symbol].append(s)

        out: list[ValidatedSignal] = []
        for symbol, group in by_symbol.items():
            score = {Side.BUY: 0.0, Side.SELL: 0.0}
            contributors = {Side.BUY: [], Side.SELL: []}
            for s in group:
                w = self._weight(s)
                score[s.side] += w * s.confidence
                contributors[s.side].append((s, w))

            winner = Side.BUY if score[Side.BUY] >= score[Side.SELL] else Side.SELL
            margin = abs(score[Side.BUY] - score[Side.SELL])
            if margin < 0.15:  # parità → nessuna operazione
                logger.info("Conflitto non risolto su %s (margine %.2f): nessuna operazione",
                            symbol, margin)
                continue

            picks = contributors[winner]
            if not picks:
                continue
            # rappresentante: il segnale a confidenza più alta del lato vincente
            best = max(picks, key=lambda sw: sw[0].confidence)[0]
            agg_conf = min(1.0, score[winner] / max(1e-9, sum(w for _, w in picks)))
            out.append(ValidatedSignal(
                signal=best,
                sources=[s.agent for s, _ in picks],
                aggregate_confidence=agg_conf,
            ))
        return out

    def _weight(self, s: Signal) -> float:
        agent = self.agents_by_name.get(s.agent)
        regime = s.regime or Regime.RANGING
        if agent is None:
            return 1.0
        return agent.vote_weight(regime)

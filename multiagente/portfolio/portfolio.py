"""PortfolioAgent — PnL, performance, loop di feedback (ARCHITETTURA.md §5.5, §9).

Mantiene le posizioni, fa mark-to-market, attribuisce il PnL all'agente
d'origine e, alla chiusura di una posizione, retroalimenta gli agenti
(``record_outcome``) per l'auto-adattamento e il peso di voto.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..core.agent import StrategyAgent
from ..core.types import Fill, Regime, Side

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    stop: float
    target: float
    source_agent: str
    regime: Regime
    fees: float = 0.0


@dataclass
class PortfolioState:
    cash: float
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def equity(self) -> float:
        return self.cash + self.realized_pnl


class PortfolioAgent:
    def __init__(self, capital: float, agents_by_name: dict[str, StrategyAgent]) -> None:
        self.state = PortfolioState(cash=capital)
        self.agents_by_name = agents_by_name

    def on_fill(self, fill: Fill, stop: float, target: float, source_agent: str, regime: Regime) -> None:
        """Apre/aggiorna una posizione su un fill."""
        self.state.realized_pnl -= fill.fee
        self.state.positions[fill.symbol] = Position(
            symbol=fill.symbol, side=fill.side, quantity=fill.quantity,
            entry_price=fill.price, stop=stop, target=target,
            source_agent=source_agent, regime=regime, fees=fill.fee,
        )

    def mark_to_market(self, prices: dict[str, float]) -> None:
        """Chiude le posizioni che hanno toccato stop o target; retroalimenta gli agenti."""
        for symbol, pos in list(self.state.positions.items()):
            px = prices.get(symbol)
            if px is None:
                continue
            hit_target = (pos.side is Side.BUY and px >= pos.target) or (
                pos.side is Side.SELL and px <= pos.target)
            hit_stop = (pos.side is Side.BUY and px <= pos.stop) or (
                pos.side is Side.SELL and px >= pos.stop)
            if hit_target or hit_stop:
                self._close(symbol, px)

    def _close(self, symbol: str, exit_price: float) -> None:
        pos = self.state.positions.pop(symbol)
        sign = 1 if pos.side is Side.BUY else -1
        pnl = sign * (exit_price - pos.entry_price) * pos.quantity - pos.fees
        self.state.realized_pnl += pnl
        logger.info("Chiusa %s da %s: PnL=%.2f (regime=%s)", symbol, pos.source_agent, pnl, pos.regime.value)
        # Loop di feedback → auto-adattamento e peso di voto.
        agent = self.agents_by_name.get(pos.source_agent)
        if agent is not None:
            agent.record_outcome(pos.regime, pnl)

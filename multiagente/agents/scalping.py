"""Desk Scalping — agenti QUANT a bassa latenza (ARCHITETTURA.md §5.2).

Catturano micro-movimenti sfruttando microstruttura e flusso. Gate costi
rigoroso: l'edge atteso deve superare spread + 2·fee. Ammessi solo su profili T1.
"""

from __future__ import annotations

from ..core.agent import StrategyAgent
from ..core.types import (
    Horizon,
    LiquidityTier,
    Regime,
    Side,
    Signal,
    TaskContext,
)

# Fee per lato in basis point (modello illustrativo).
_FEE_BPS = 1.0


class OrderFlowScalper(StrategyAgent):
    """Segue lo sbilanciamento del book quando supera una soglia adattiva."""

    horizon = Horizon.SCALPING

    def __init__(self) -> None:
        super().__init__("OrderFlowScalper")
        # soglia adattiva di imbalance, con guardrail
        self.register_param("imbalance_threshold", 0.4, 0.2, 0.8)
        self.register_param("target_bps", 5.0, 2.0, 15.0)

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined:
            return None
        profile, snap = ctx.profile, ctx.snapshot
        # Ammesso solo su massima liquidità.
        if profile.liquidity_tier != LiquidityTier.T1:
            return None
        thr = self.param("imbalance_threshold")
        if abs(snap.book_imbalance) < thr:
            return None

        side = Side.BUY if snap.book_imbalance > 0 else Side.SELL
        target_bps = self.param("target_bps")
        entry = snap.ask if side is Side.BUY else snap.bid

        # Gate costi: edge atteso > spread + 2·fee.
        cost_bps = snap.spread_bps + 2 * _FEE_BPS
        if target_bps <= cost_bps:
            return None

        sign = 1 if side is Side.BUY else -1
        target = entry * (1 + sign * target_bps / 1e4)
        stop = entry * (1 - sign * (target_bps * 0.6) / 1e4)
        return Signal(
            agent=self.name, symbol=snap.symbol, horizon=self.horizon, side=side,
            confidence=min(1.0, abs(snap.book_imbalance)), entry=entry, stop=stop,
            target=target, size_hint=0.1, tif="IOC", regime=ctx.regime.regime,
            rationale=f"order-flow imbalance={snap.book_imbalance:.2f}>{thr:.2f}",
        )

    def _adapt(self, regime: Regime, pnl: float) -> None:
        # Se perde, alza la soglia (più selettivo); se vince, la abbassa un po'.
        self._nudge_param("imbalance_threshold", 0.98 if pnl >= 0 else 1.03)


class SpreadMeanReversionScalper(StrategyAgent):
    """Mean-reversion su profili a bassissima volatilità (es. stablecoin)."""

    horizon = Horizon.SCALPING

    def __init__(self) -> None:
        super().__init__("SpreadMeanReversionScalper")
        self.register_param("deviation_bps", 3.0, 1.0, 10.0)

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined:
            return None
        snap, profile = ctx.snapshot, ctx.profile
        if profile.liquidity_tier != LiquidityTier.T1:
            return None
        # Opera solo in regime ranging / bassa volatilità.
        if ctx.regime.regime not in (Regime.RANGING,):
            return None
        series = snap.ohlcv.get("1m") or [snap.mid]
        mean = sum(series) / len(series)
        dev_bps = (snap.mid - mean) / mean * 1e4 if mean else 0.0
        if abs(dev_bps) < self.param("deviation_bps"):
            return None
        side = Side.SELL if dev_bps > 0 else Side.BUY  # ritorno alla media
        sign = 1 if side is Side.BUY else -1
        entry = snap.mid
        target = mean
        stop = entry * (1 - sign * abs(dev_bps) / 1e4)
        return Signal(
            agent=self.name, symbol=snap.symbol, horizon=self.horizon, side=side,
            confidence=min(1.0, abs(dev_bps) / 10.0), entry=entry, stop=stop,
            target=target, size_hint=0.1, tif="IOC", regime=ctx.regime.regime,
            rationale=f"mean-reversion dev={dev_bps:.1f}bps",
        )


def build_scalping_desk() -> list[StrategyAgent]:
    return [OrderFlowScalper(), SpreadMeanReversionScalper()]

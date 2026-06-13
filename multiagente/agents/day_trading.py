"""Desk Day Trading — agenti IBRIDI specializzati per regime (ARCHITETTURA.md §5.3).

Ogni agente è attivato solo nel regime per cui è specializzato. Usa indicatori
quant (proxy semplificati nello scaffold) modulati dal sentiment LLM.
"""

from __future__ import annotations

from ..core.agent import StrategyAgent
from ..core.types import Horizon, Regime, Side, Signal, TaskContext


def _atr_proxy(ctx: TaskContext) -> float:
    """Proxy di ATR: usa lo spread e la volatilità del profilo come scala dello stop."""
    base = ctx.snapshot.mid
    mult = {"low": 0.004, "mid": 0.008, "high": 0.015, "extreme": 0.03}
    return base * mult.get(ctx.profile.volatility_bucket.value, 0.008)


class TrendIntradayAgent(StrategyAgent):
    """Attivo in trending_*: entra su pullback nella direzione del trend."""

    horizon = Horizon.DAY_TRADING

    def __init__(self) -> None:
        super().__init__("TrendIntraday")
        self.register_param("stop_atr_mult", 1.5, 0.8, 3.0)
        self.register_param("rr", 2.0, 1.2, 4.0)  # rapporto rischio/rendimento

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined:
            return None
        regime = ctx.regime.regime
        if regime not in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            return None
        side = Side.BUY if regime is Regime.TRENDING_UP else Side.SELL
        # Conferma da sentiment: non andare contro un sentiment forte opposto.
        if ctx.sentiment and ctx.sentiment.confidence > 0.5:
            if (side is Side.BUY and ctx.sentiment.polarity < -0.3) or (
                side is Side.SELL and ctx.sentiment.polarity > 0.3
            ):
                return None
        entry = ctx.snapshot.mid
        atr = _atr_proxy(ctx)
        sign = 1 if side is Side.BUY else -1
        stop = entry - sign * self.param("stop_atr_mult") * atr
        target = entry + sign * self.param("stop_atr_mult") * self.param("rr") * atr
        conf = ctx.regime.probability
        return Signal(
            agent=self.name, symbol=ctx.snapshot.symbol, horizon=self.horizon, side=side,
            confidence=conf, entry=entry, stop=stop, target=target, size_hint=0.3,
            tif="DAY", regime=regime, rationale=f"trend {regime.value} prob={conf:.2f}",
        )

    def _adapt(self, regime: Regime, pnl: float) -> None:
        # Se perde, allarga lo stop (meno stop-out da rumore).
        self._nudge_param("stop_atr_mult", 1.05 if pnl < 0 else 0.99)


class RangeReversionAgent(StrategyAgent):
    """Attivo in ranging: fade dei bordi del range."""

    horizon = Horizon.DAY_TRADING

    def __init__(self) -> None:
        super().__init__("RangeReversion")
        self.register_param("band_pct", 0.01, 0.003, 0.03)

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined or ctx.regime.regime is not Regime.RANGING:
            return None
        series = ctx.snapshot.ohlcv.get("1m") or [ctx.snapshot.mid]
        mean = sum(series) / len(series)
        band = mean * self.param("band_pct")
        mid = ctx.snapshot.mid
        if mid > mean + band:
            side = Side.SELL
        elif mid < mean - band:
            side = Side.BUY
        else:
            return None
        sign = 1 if side is Side.BUY else -1
        entry = mid
        target = mean
        stop = entry - sign * band * 1.5
        return Signal(
            agent=self.name, symbol=ctx.snapshot.symbol, horizon=self.horizon, side=side,
            confidence=0.55, entry=entry, stop=stop, target=target, size_hint=0.25,
            tif="DAY", regime=ctx.regime.regime, rationale="range fade",
        )


def build_day_trading_desk() -> list[StrategyAgent]:
    return [TrendIntradayAgent(), RangeReversionAgent()]

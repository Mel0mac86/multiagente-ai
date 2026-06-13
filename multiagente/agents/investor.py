"""Desk Investor — orizzonte giorni–mesi (ARCHITETTURA.md §5.4).

Comprende un agente fondamentale LLM (tesi d'investimento strutturata), un
trend-follower quant di lungo periodo e un MacroRegimeAgent che definisce il
risk-on/risk-off globale (potere di veto sui desk veloci, vedi §8).
"""

from __future__ import annotations

from ..core.agent import StrategyAgent
from ..core.types import Horizon, Regime, Side, Signal, TaskContext
from ..llm.claude_client import ClaudeClient

_THESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "conviction": {"type": "number"},  # 0..1
        "thesis": {"type": "string"},
        "invalidation": {"type": "string"},
    },
    "required": ["stance", "conviction", "thesis", "invalidation"],
    "additionalProperties": False,
}

_THESIS_SYSTEM = (
    "Sei un analista d'investimento di lungo periodo. Costruisci una tesi prudente "
    "basata su fondamentali e macro, con condizioni di invalidazione esplicite. "
    "Alta conviction solo con evidenze concordi."
)


class FundamentalThesisAgent(StrategyAgent):
    """Agente LLM: tesi d'investimento strutturata su orizzonte lungo."""

    horizon = Horizon.INVESTOR

    def __init__(self, llm: ClaudeClient) -> None:
        super().__init__("FundamentalThesis")
        self.llm = llm

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined:
            return None
        result = None
        if self.llm.available:
            prompt = (
                f"Strumento: {ctx.profile.symbol} ({ctx.profile.asset_class.value}). "
                f"Cluster: {ctx.profile.correlation_cluster}. "
                f"Sentiment corrente: polarity={ctx.sentiment.polarity if ctx.sentiment else 0:.2f}. "
                "Formula una tesi d'investimento."
            )
            result = self.llm.structured(system=_THESIS_SYSTEM, prompt=prompt, schema=_THESIS_SCHEMA)
        if result is None:
            return None  # senza LLM, questo agente si astiene (nessun fallback inventato)

        stance = result["stance"]
        if stance == "neutral":
            return None
        side = Side.BUY if stance == "bullish" else Side.SELL
        conv = float(result["conviction"])
        entry = ctx.snapshot.mid
        sign = 1 if side is Side.BUY else -1
        # Stop/target ampi (orizzonte lungo).
        stop = entry * (1 - sign * 0.12)
        target = entry * (1 + sign * 0.30)
        return Signal(
            agent=self.name, symbol=ctx.snapshot.symbol, horizon=self.horizon, side=side,
            confidence=conv, entry=entry, stop=stop, target=target, size_hint=0.5,
            tif="GTC", regime=ctx.regime.regime,
            rationale=f"tesi: {result['thesis'][:140]} | invalida: {result['invalidation'][:80]}",
        )


class TrendFollowingAgent(StrategyAgent):
    """Trend-following di lungo periodo (proxy: direzione del regime)."""

    horizon = Horizon.INVESTOR

    def __init__(self) -> None:
        super().__init__("TrendFollowing")

    def evaluate(self, ctx: TaskContext) -> Signal | None:
        if self.quarantined:
            return None
        regime = ctx.regime.regime
        if regime not in (Regime.TRENDING_UP, Regime.TRENDING_DOWN):
            return None
        side = Side.BUY if regime is Regime.TRENDING_UP else Side.SELL
        entry = ctx.snapshot.mid
        sign = 1 if side is Side.BUY else -1
        stop = entry * (1 - sign * 0.10)
        target = entry * (1 + sign * 0.25)
        return Signal(
            agent=self.name, symbol=ctx.snapshot.symbol, horizon=self.horizon, side=side,
            confidence=0.5, entry=entry, stop=stop, target=target, size_hint=0.4,
            tif="GTC", regime=regime, rationale=f"trend di lungo periodo {regime.value}",
        )


def build_investor_desk(llm: ClaudeClient) -> list[StrategyAgent]:
    return [FundamentalThesisAgent(llm), TrendFollowingAgent()]

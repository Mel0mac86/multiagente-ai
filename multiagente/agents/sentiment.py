"""NewsSentimentAgent — agente LLM (ARCHITETTURA.md §5.1).

Trasforma news/eventi in un ``SentimentSignal`` strutturato. Usa Claude con
output JSON (schema) e, dove disponibili, tool per fetch headline / calendario
economico. Senza LLM disponibile, ricade su un'euristica neutra: non blocca mai.
"""

from __future__ import annotations

import logging
import time

from ..core.types import Horizon, NewsSensitivity, PairProfile, SentimentSignal
from ..llm.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "polarity": {"type": "number"},          # -1..+1
        "confidence": {"type": "number"},         # 0..1
        "impact_horizon": {"type": "string", "enum": ["scalping", "day_trading", "investor"]},
        "imminent_high_impact_event": {"type": "boolean"},
        "minutes_to_event": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["polarity", "confidence", "impact_horizon", "imminent_high_impact_event", "rationale"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Sei un analista di sentiment di mercato. Dato uno strumento e il contesto news, "
    "restituisci un giudizio strutturato e prudente. Usa polarity in [-1,1], "
    "confidence in [0,1]. Segnala eventi macro imminenti ad alto impatto."
)

# Esempio di tool che l'orchestratore eseguirebbe lato applicazione.
_TOOLS = [
    {
        "name": "fetch_headlines",
        "description": "Recupera le ultime headline per uno strumento o asset.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "economic_calendar",
        "description": "Restituisce gli eventi macro imminenti rilevanti per lo strumento.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
]


class NewsSentimentAgent:
    def __init__(self, llm: ClaudeClient) -> None:
        self.llm = llm
        self.name = "NewsSentiment"

    def assess(self, profile: PairProfile, news_context: str = "") -> SentimentSignal:
        """Produce un SentimentSignal per lo strumento."""
        result = None
        if self.llm.available and profile.news_sensitivity != NewsSensitivity.LOW:
            prompt = (
                f"Strumento: {profile.symbol} (classe {profile.asset_class.value}, "
                f"cluster {profile.correlation_cluster}, sensibilità news "
                f"{profile.news_sensitivity.value}).\nContesto news:\n{news_context or '(nessuno)'}"
            )
            result = self.llm.structured(system=_SYSTEM, prompt=prompt, schema=_SCHEMA, tools=_TOOLS)

        if result is None:
            return self._heuristic(profile)

        blackout = None
        if result.get("imminent_high_impact_event") and result.get("minutes_to_event", 999) <= 15:
            blackout = time.time() + result["minutes_to_event"] * 60
        return SentimentSignal(
            symbol=profile.symbol,
            polarity=float(result["polarity"]),
            confidence=float(result["confidence"]),
            impact_horizon=Horizon(result["impact_horizon"]),
            blackout_until=blackout,
            rationale=result.get("rationale", ""),
        )

    def _heuristic(self, profile: PairProfile) -> SentimentSignal:
        """Fallback offline: sentiment neutro a bassa confidenza."""
        return SentimentSignal(
            symbol=profile.symbol,
            polarity=0.0,
            confidence=0.2,
            impact_horizon=Horizon.DAY_TRADING,
            rationale="fallback euristico (LLM non disponibile)",
        )

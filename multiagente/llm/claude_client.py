"""Wrapper per Claude usato dagli agenti LLM.

Caratteristiche (ARCHITETTURA.md §5.1, §7.2):
  * adaptive thinking (`thinking={"type": "adaptive"}`) per i task di ragionamento;
  * output **strutturato** via ``output_config.format`` (JSON machine-readable);
  * **fallback** di modello (es. claude-opus-4-8 → claude-sonnet-4-6) e poi
    fallback euristico se l'LLM non è disponibile o rifiuta;
  * circuit breaker sulle chiamate API.

Se non c'è una chiave API, ``available`` è False e i chiamanti devono usare la
loro euristica locale: gli agenti LLM non bloccano mai i desk quant.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import LLMConfig
from ..core.faults import CircuitBreaker, retry_with_backoff
from ..config import FaultConfig

logger = logging.getLogger(__name__)

try:  # l'SDK è opzionale in modalità offline
    import anthropic
except ImportError:  # pragma: no cover - dipendenza opzionale
    anthropic = None  # type: ignore[assignment]


class ClaudeClient:
    """Client Claude con fallback di modello e output strutturato."""

    def __init__(self, cfg: LLMConfig, fault_cfg: FaultConfig | None = None) -> None:
        self.cfg = cfg
        self._fault_cfg = fault_cfg or FaultConfig()
        self._breaker = CircuitBreaker("claude", self._fault_cfg)
        self._client: Any | None = None
        if cfg.enabled and anthropic is not None:
            self._client = anthropic.Anthropic(api_key=cfg.api_key, timeout=cfg.timeout_s)

    @property
    def available(self) -> bool:
        return self._client is not None

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Chiede a Claude un output JSON conforme a ``schema``.

        Restituisce il dict parsato, oppure ``None`` se l'LLM non è disponibile,
        rifiuta, o fallisce dopo i retry (il chiamante usa il fallback euristico).
        """
        if not self.available:
            return None

        primary = self.cfg.model
        for model in (primary, self.cfg.fallback_model):
            try:
                return self._breaker.call(lambda m=model: self._call(m, system, prompt, schema, tools))
            except Exception as exc:  # noqa: BLE001 - degradazione controllata
                logger.warning("Claude (%s) ha fallito: %s; provo il fallback", model, exc)
        logger.warning("Tutti i modelli Claude hanno fallito; uso fallback euristico")
        return None

    def _call(
        self,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        def _do() -> dict[str, Any] | None:
            assert self._client is not None
            kwargs: dict[str, Any] = dict(
                model=model,
                max_tokens=self.cfg.max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}],
            )
            if tools:
                kwargs["tools"] = tools
            resp = self._client.messages.create(**kwargs)

            # Gestione del refusal (ARCHITETTURA.md §7.2): tratta come "nessun segnale".
            if getattr(resp, "stop_reason", None) == "refusal":
                logger.info("Claude ha rifiutato la richiesta; nessun segnale")
                return None

            text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
            if not text:
                return None
            return json.loads(text)

        return retry_with_backoff(_do, self._fault_cfg)

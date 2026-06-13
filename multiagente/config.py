"""Configurazione globale del sistema e feature flag.

I valori sono letti dalle variabili d'ambiente (vedi .env.example) con default
sicuri: modalità *paper* e nessun ordine reale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMConfig:
    """Configurazione degli agenti LLM (Claude)."""

    api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None)
    model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "claude-opus-4-8"))
    fallback_model: str = field(
        default_factory=lambda: os.environ.get("LLM_FALLBACK_MODEL", "claude-sonnet-4-6")
    )
    # max_tokens prudente per output strutturati (no streaming richiesto sotto ~16k).
    max_tokens: int = 4096
    timeout_s: float = 30.0

    @property
    def enabled(self) -> bool:
        """True se è disponibile una chiave: altrimenti si usa il fallback euristico."""
        return bool(self.api_key)


@dataclass(frozen=True)
class RiskConfig:
    """Limiti di rischio applicati dal RiskManager."""

    risk_per_trade: float = 0.005        # 0.5% del capitale a rischio per trade
    max_gross_exposure: float = 3.0      # esposizione lorda max (in multipli del capitale)
    max_cluster_exposure: float = 1.0    # esposizione max per cluster di correlazione
    max_daily_drawdown: float = 0.04     # 4% → trigger del kill switch
    default_leverage_cap: float = 1.0


@dataclass(frozen=True)
class FaultConfig:
    """Parametri di circuit breaker / retry."""

    breaker_failure_threshold: int = 5
    breaker_cooldown_s: float = 30.0
    retry_max_attempts: int = 4
    retry_base_delay_s: float = 0.5
    heartbeat_timeout_s: float = 10.0
    stale_data_timeout_s: float = 5.0


@dataclass(frozen=True)
class Settings:
    """Contenitore della configurazione di sistema."""

    trading_mode: str = field(default_factory=lambda: os.environ.get("TRADING_MODE", "paper"))
    capital: float = 100_000.0
    llm: LLMConfig = field(default_factory=LLMConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    fault: FaultConfig = field(default_factory=FaultConfig)

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live"


# Istanza condivisa di default.
SETTINGS = Settings()

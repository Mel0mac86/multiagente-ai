"""Gestione dei guasti: circuit breaker, retry con backoff, health monitor,
kill switch. Vedi ARCHITETTURA.md §7.2.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from ..config import FaultConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BreakerState(str, Enum):
    CLOSED = "closed"        # tutto ok
    OPEN = "open"            # in avaria: le chiamate falliscono subito
    HALF_OPEN = "half_open"  # in prova dopo il cooldown


class CircuitOpenError(RuntimeError):
    """Sollevata quando il breaker è aperto."""


class CircuitBreaker:
    """Circuit breaker per una dipendenza esterna (feed, broker, LLM).

    CLOSED → (N fallimenti) → OPEN → (cooldown) → HALF_OPEN → (successo) → CLOSED
    """

    def __init__(self, name: str, cfg: FaultConfig) -> None:
        self.name = name
        self.cfg = cfg
        self.state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    def _allow(self) -> bool:
        if self.state == BreakerState.OPEN:
            if time.time() - self._opened_at >= self.cfg.breaker_cooldown_s:
                self.state = BreakerState.HALF_OPEN
                return True
            return False
        return True

    def call(self, fn: Callable[[], T]) -> T:
        if not self._allow():
            raise CircuitOpenError(f"breaker '{self.name}' aperto")
        try:
            result = fn()
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result

    def _on_success(self) -> None:
        self._failures = 0
        if self.state != BreakerState.CLOSED:
            logger.info("Breaker '%s' richiuso", self.name)
        self.state = BreakerState.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.cfg.breaker_failure_threshold:
            self.state = BreakerState.OPEN
            self._opened_at = time.time()
            logger.warning("Breaker '%s' APERTO dopo %d fallimenti", self.name, self._failures)


def retry_with_backoff(fn: Callable[[], T], cfg: FaultConfig) -> T:
    """Esegue ``fn`` con retry e backoff esponenziale + jitter."""
    last_exc: Exception | None = None
    for attempt in range(cfg.retry_max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retry generico controllato
            last_exc = exc
            delay = cfg.retry_base_delay_s * (2**attempt) + random.uniform(0, cfg.retry_base_delay_s)
            logger.warning("Tentativo %d fallito (%s); riprovo tra %.2fs", attempt + 1, exc, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


class HealthMonitor:
    """Traccia gli heartbeat degli agenti; segnala chi è silente."""

    def __init__(self, cfg: FaultConfig) -> None:
        self.cfg = cfg
        self._last_beat: dict[str, float] = {}

    def heartbeat(self, agent: str) -> None:
        self._last_beat[agent] = time.time()

    def unhealthy(self) -> list[str]:
        now = time.time()
        return [
            name
            for name, ts in self._last_beat.items()
            if now - ts > self.cfg.heartbeat_timeout_s
        ]


class KillSwitch:
    """Interruttore di sicurezza globale (ARCHITETTURA.md §7.2).

    Quando attivo: blocca i nuovi ordini e segnala di azzerare le posizioni.
    """

    def __init__(self) -> None:
        self._engaged = False
        self._reason = ""

    @property
    def engaged(self) -> bool:
        return self._engaged

    def engage(self, reason: str) -> None:
        if not self._engaged:
            logger.critical("KILL SWITCH ATTIVATO: %s", reason)
        self._engaged = True
        self._reason = reason

    def reset(self) -> None:
        logger.warning("Kill switch resettato (era: %s)", self._reason)
        self._engaged = False
        self._reason = ""

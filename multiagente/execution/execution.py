"""ExecutionAgent + broker adapter (ARCHITETTURA.md §5.5).

Traduce gli Order in esecuzione. Lo scaffold include un PaperBroker che riempie
gli ordini al prezzo corrente con uno slippage simulato; l'adapter live va
implementato qui mantenendo la stessa interfaccia. Retry/idempotenza tramite
``client_order_id``.
"""

from __future__ import annotations

import abc
import logging

from ..config import FaultConfig
from ..core.faults import CircuitBreaker, retry_with_backoff
from ..core.types import Fill, MarketSnapshot, Order, Side

logger = logging.getLogger(__name__)


class BrokerAdapter(abc.ABC):
    name: str

    @abc.abstractmethod
    def submit(self, order: Order, snap: MarketSnapshot) -> Fill:
        """Invia l'ordine e ritorna il fill (alza eccezione su errore transitorio)."""


class PaperBroker(BrokerAdapter):
    """Broker simulato: riempie al prezzo corrente con slippage modellato."""

    name = "paper"

    def __init__(self, slippage_bps: float = 1.0, fee_bps: float = 1.0) -> None:
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps
        self._seen: set[str] = set()  # idempotenza per client_order_id

    def submit(self, order: Order, snap: MarketSnapshot) -> Fill:
        if order.client_order_id in self._seen:
            raise RuntimeError("ordine duplicato (idempotenza)")
        ref = snap.ask if order.side is Side.BUY else snap.bid
        sign = 1 if order.side is Side.BUY else -1
        price = ref * (1 + sign * self.slippage_bps / 1e4)
        fee = abs(price * order.quantity) * self.fee_bps / 1e4
        self._seen.add(order.client_order_id)
        return Fill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee=fee,
        )


class ExecutionAgent:
    def __init__(self, broker: BrokerAdapter, cfg: FaultConfig) -> None:
        self.broker = broker
        self.cfg = cfg
        self._breaker = CircuitBreaker(f"broker:{broker.name}", cfg)

    def execute(self, order: Order, snap: MarketSnapshot) -> Fill | None:
        """Esegue con retry+breaker. Ritorna None se l'esecuzione non riesce."""
        try:
            return self._breaker.call(
                lambda: retry_with_backoff(lambda: self.broker.submit(order, snap), self.cfg)
            )
        except Exception as exc:  # noqa: BLE001 - degradazione controllata
            logger.error("Esecuzione fallita per %s: %s", order.symbol, exc)
            return None

"""Message bus pub/sub + blackboard condivisa.

Disaccoppia produttori e consumatori (ARCHITETTURA.md §8). Implementazione
sincrona in-process per lo scaffold; in produzione si sostituirebbe con un
broker (Redis Streams, NATS, Kafka…) mantenendo la stessa interfaccia.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class MessageBus:
    """Bus pub/sub minimale per topic con dead-letter queue."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self.dead_letter: deque[tuple[str, Any, Exception]] = deque(maxlen=1000)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, message: Any) -> None:
        """Consegna a tutti i subscriber. Gli errori non bloccano gli altri."""
        for handler in self._subs.get(topic, ()):
            try:
                handler(message)
            except Exception as exc:  # noqa: BLE001 - isolamento dei subscriber
                logger.exception("Subscriber su %s ha fallito: %s", topic, exc)
                self.dead_letter.append((topic, message, exc))


class Blackboard:
    """Memoria condivisa: regime corrente, sentiment, stato portafoglio, blackout.

    Letta da tutti gli agenti senza accoppiamento diretto (ARCHITETTURA.md §8).
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def namespaced(self, ns: str, key: str, value: Any) -> None:
        self._store[f"{ns}:{key}"] = value

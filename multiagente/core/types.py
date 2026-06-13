"""Tipi condivisi: enum e dataclass usati da tutti gli agenti.

Questi tipi sono il "contratto" tra agenti. Modificarli con cautela: il
Validator (orchestrator/validator.py) valida i Signal contro questo schema.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
# Orizzonti, mercati, regimi, classi di profilo                               #
# --------------------------------------------------------------------------- #
class Horizon(str, Enum):
    """Orizzonte operativo di un desk/agente."""

    SCALPING = "scalping"        # secondi – minuti
    DAY_TRADING = "day_trading"  # minuti – ore
    INVESTOR = "investor"        # giorni – mesi


class AssetClass(str, Enum):
    CRYPTO = "crypto"
    FOREX = "forex"
    EQUITY = "equity"
    COMMODITY = "commodity"


class LiquidityTier(str, Enum):
    T1 = "T1"  # altissima
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"  # illiquida


class VolatilityBucket(str, Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"
    EXTREME = "extreme"


class NewsSensitivity(str, Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    NEWS_DRIVEN = "news_driven"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


# --------------------------------------------------------------------------- #
# Profilo di coppia (output del PairClassifier)                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PairProfile:
    """Classificazione di uno strumento. Parametrizza il comportamento dei desk.

    Vedi ARCHITETTURA.md §4. Evita la generalizzazione: ogni strumento porta con
    sé spread, liquidità, volatilità, orari e sensibilità alle news.
    """

    symbol: str
    asset_class: AssetClass
    liquidity_tier: LiquidityTier
    typical_spread_bps: float
    volatility_bucket: VolatilityBucket
    news_sensitivity: NewsSensitivity
    correlation_cluster: str
    tick_size: float
    lot_size: float
    leverage_cap: float
    session_profile: str = "24/7"  # es. "24/7", "fx_sessions", "nyse_rth"


# --------------------------------------------------------------------------- #
# Snapshot di mercato (output del MarketDataAgent)                            #
# --------------------------------------------------------------------------- #
@dataclass
class MarketSnapshot:
    """Stato di mercato normalizzato per uno strumento a un istante."""

    symbol: str
    ts: float
    bid: float
    ask: float
    last: float
    # OHLCV per timeframe, es. {"1m": [...], "1h": [...]}; valori illustrativi.
    ohlcv: dict[str, list[float]] = field(default_factory=dict)
    book_imbalance: float = 0.0   # >0 = pressione in acquisto
    degraded: bool = False        # True se i dati sono stantii / da feed secondario

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return float("inf")
        return (self.ask - self.bid) / self.mid * 1e4


# --------------------------------------------------------------------------- #
# Segnali, regime, sentiment                                                  #
# --------------------------------------------------------------------------- #
@dataclass
class RegimeEstimate:
    symbol: str
    regime: Regime
    probability: float
    ts: float = field(default_factory=time.time)


@dataclass
class SentimentSignal:
    """Output del NewsSentimentAgent (LLM)."""

    symbol: str
    polarity: float          # -1..+1
    confidence: float        # 0..1
    impact_horizon: Horizon
    blackout_until: float | None = None  # epoch: niente trading fino a qui
    rationale: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class Signal:
    """Proposta di un agente di strategia. NON è un ordine: va validata."""

    agent: str
    symbol: str
    horizon: Horizon
    side: Side
    confidence: float                 # 0..1
    entry: float
    stop: float
    target: float
    size_hint: float                  # frazione/numero indicativo, rifinito dal Risk
    tif: str = "GTC"                  # es. IOC per scalping, DAY per day trading
    rationale: str = ""
    regime: Regime | None = None
    ts: float = field(default_factory=time.time)
    signal_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def edge_bps(self) -> float:
        """Edge atteso (target vs entry) in basis point, usato dal gate costi."""
        if self.entry <= 0:
            return 0.0
        return abs(self.target - self.entry) / self.entry * 1e4


@dataclass
class ValidatedSignal:
    """Segnale che ha superato il Validator (eventualmente fuso da più segnali)."""

    signal: Signal
    sources: list[str] = field(default_factory=list)  # agenti che hanno contribuito
    aggregate_confidence: float = 0.0


# --------------------------------------------------------------------------- #
# Ordini ed esecuzione                                                        #
# --------------------------------------------------------------------------- #
@dataclass
class Order:
    """Ordine dimensionato dal RiskManager, pronto per l'ExecutionAgent."""

    symbol: str
    side: Side
    quantity: float
    order_type: str           # "limit" | "market"
    limit_price: float | None
    stop: float
    target: float
    client_order_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fill:
    client_order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float = 0.0
    ts: float = field(default_factory=time.time)


# --------------------------------------------------------------------------- #
# Contesto del task (pubblicato dal Router sul bus)                           #
# --------------------------------------------------------------------------- #
@dataclass
class TaskContext:
    """Contesto completo per la valutazione di uno strumento da parte dei desk."""

    snapshot: MarketSnapshot
    profile: PairProfile
    regime: RegimeEstimate
    sentiment: SentimentSignal | None = None
    params: dict[str, Any] = field(default_factory=dict)  # parametri per-profilo/regime

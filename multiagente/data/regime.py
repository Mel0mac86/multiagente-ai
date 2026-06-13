"""RegimeDetectorAgent (ARCHITETTURA.md §5.1).

Etichetta il regime corrente per coppia/timeframe. Lo scaffold usa una semplice
euristica su volatilità/imbalance; in produzione si userebbe un modello a stati
(es. HMM) o un classificatore su feature (ADX, ampiezza di banda, autocorr.).
"""

from __future__ import annotations

from ..core.types import (
    MarketSnapshot,
    PairProfile,
    Regime,
    RegimeEstimate,
    SentimentSignal,
    VolatilityBucket,
)


class RegimeDetectorAgent:
    def regime(
        self,
        snap: MarketSnapshot,
        profile: PairProfile,
        sentiment: SentimentSignal | None = None,
    ) -> RegimeEstimate:
        # Un evento news imminente domina: regime news_driven.
        if sentiment is not None and sentiment.blackout_until is not None:
            return RegimeEstimate(snap.symbol, Regime.NEWS_DRIVEN, probability=0.9)

        # Volatilità estrema → high_volatility.
        if profile.volatility_bucket in (VolatilityBucket.EXTREME, VolatilityBucket.HIGH):
            if abs(snap.book_imbalance) < 0.2:
                return RegimeEstimate(snap.symbol, Regime.HIGH_VOLATILITY, probability=0.6)

        # Imbalance del book come proxy del trend di breve.
        if snap.book_imbalance > 0.35:
            return RegimeEstimate(snap.symbol, Regime.TRENDING_UP, probability=0.65)
        if snap.book_imbalance < -0.35:
            return RegimeEstimate(snap.symbol, Regime.TRENDING_DOWN, probability=0.65)

        return RegimeEstimate(snap.symbol, Regime.RANGING, probability=0.6)

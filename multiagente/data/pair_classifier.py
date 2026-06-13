"""PairClassifierAgent + profili di coppia (ARCHITETTURA.md §4, §5.1).

Assegna a ogni strumento un ``PairProfile`` con attributi quantitativi che
parametrizzano il comportamento dei desk. Lo scaffold include un registro
statico di profili d'esempio per i 4 mercati; in produzione i bucket
(liquidità, volatilità, spread) sarebbero calcolati da statistiche rolling e
arricchiti opzionalmente da un passaggio LLM per cluster/news_sensitivity.
"""

from __future__ import annotations

from ..core.types import (
    AssetClass,
    LiquidityTier,
    NewsSensitivity,
    PairProfile,
    VolatilityBucket,
)


def _p(**kw) -> PairProfile:
    return PairProfile(**kw)


# Registro di esempio: copre crypto, forex, azioni/indici, materie prime.
_PROFILES: dict[str, PairProfile] = {
    # --- Crypto (24/7) ---------------------------------------------------- #
    "BTC/USDT": _p(symbol="BTC/USDT", asset_class=AssetClass.CRYPTO, liquidity_tier=LiquidityTier.T1,
                   typical_spread_bps=1.0, volatility_bucket=VolatilityBucket.HIGH,
                   news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="crypto_l1",
                   tick_size=0.1, lot_size=0.0001, leverage_cap=5.0, session_profile="24/7"),
    "ETH/USDT": _p(symbol="ETH/USDT", asset_class=AssetClass.CRYPTO, liquidity_tier=LiquidityTier.T1,
                   typical_spread_bps=1.5, volatility_bucket=VolatilityBucket.HIGH,
                   news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="crypto_l1",
                   tick_size=0.01, lot_size=0.001, leverage_cap=5.0, session_profile="24/7"),
    "USDT/USDC": _p(symbol="USDT/USDC", asset_class=AssetClass.CRYPTO, liquidity_tier=LiquidityTier.T1,
                    typical_spread_bps=0.5, volatility_bucket=VolatilityBucket.LOW,
                    news_sensitivity=NewsSensitivity.LOW, correlation_cluster="stablecoin",
                    tick_size=0.0001, lot_size=1.0, leverage_cap=1.0, session_profile="24/7"),
    # --- Forex (sessioni) ------------------------------------------------- #
    "EUR/USD": _p(symbol="EUR/USD", asset_class=AssetClass.FOREX, liquidity_tier=LiquidityTier.T1,
                  typical_spread_bps=0.5, volatility_bucket=VolatilityBucket.LOW,
                  news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="usd_majors",
                  tick_size=0.00001, lot_size=1000.0, leverage_cap=30.0, session_profile="fx_sessions"),
    "USD/TRY": _p(symbol="USD/TRY", asset_class=AssetClass.FOREX, liquidity_tier=LiquidityTier.T3,
                  typical_spread_bps=8.0, volatility_bucket=VolatilityBucket.EXTREME,
                  news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="fx_exotics",
                  tick_size=0.0001, lot_size=1000.0, leverage_cap=10.0, session_profile="fx_sessions"),
    # --- Azioni / Indici (orari di borsa) --------------------------------- #
    "AAPL": _p(symbol="AAPL", asset_class=AssetClass.EQUITY, liquidity_tier=LiquidityTier.T1,
               typical_spread_bps=1.0, volatility_bucket=VolatilityBucket.MID,
               news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="us_tech",
               tick_size=0.01, lot_size=1.0, leverage_cap=2.0, session_profile="nyse_rth"),
    "SPX": _p(symbol="SPX", asset_class=AssetClass.EQUITY, liquidity_tier=LiquidityTier.T1,
              typical_spread_bps=0.8, volatility_bucket=VolatilityBucket.MID,
              news_sensitivity=NewsSensitivity.MID, correlation_cluster="us_index",
              tick_size=0.25, lot_size=1.0, leverage_cap=5.0, session_profile="nyse_rth"),
    # --- Materie prime ---------------------------------------------------- #
    "XAU/USD": _p(symbol="XAU/USD", asset_class=AssetClass.COMMODITY, liquidity_tier=LiquidityTier.T1,
                  typical_spread_bps=2.0, volatility_bucket=VolatilityBucket.MID,
                  news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="metals",
                  tick_size=0.01, lot_size=1.0, leverage_cap=20.0, session_profile="fx_sessions"),
    "WTI": _p(symbol="WTI", asset_class=AssetClass.COMMODITY, liquidity_tier=LiquidityTier.T2,
              typical_spread_bps=3.0, volatility_bucket=VolatilityBucket.HIGH,
              news_sensitivity=NewsSensitivity.HIGH, correlation_cluster="energy",
              tick_size=0.01, lot_size=1.0, leverage_cap=10.0, session_profile="nymex"),
}


class PairClassifierAgent:
    """Restituisce (con cache) il profilo di uno strumento."""

    def __init__(
        self,
        profiles: dict[str, PairProfile] | None = None,
        extra_profiles: dict[str, PairProfile] | None = None,
    ) -> None:
        self._profiles = profiles or dict(_PROFILES)
        if extra_profiles:
            self._profiles.update(extra_profiles)

    def profile(self, symbol: str) -> PairProfile | None:
        return self._profiles.get(symbol)

    def known_symbols(self) -> list[str]:
        return list(self._profiles)


def derive_profile(symbol: str, bars) -> PairProfile:
    """Stima un profilo dai dati per uno strumento non presente nel registro.

    Volatilità dal sigma dei rendimenti; asset class indovinata dal nome. Usato
    quando l'utente porta storici di strumenti non ancora mappati.
    """
    import statistics

    prices = [b.price for b in bars]
    rets = [(b - a) / a for a, b in zip(prices, prices[1:]) if a]
    sigma = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    if sigma < 0.005:
        vol = VolatilityBucket.LOW
    elif sigma < 0.015:
        vol = VolatilityBucket.MID
    elif sigma < 0.04:
        vol = VolatilityBucket.HIGH
    else:
        vol = VolatilityBucket.EXTREME

    u = symbol.upper()
    alpha = u.replace("/", "")
    # ordine: commodity prima di forex (XAUUSD è oro, non FX); poi FX a 6 lettere
    if any(k in u for k in ("BTC", "ETH", "USDT", "USDC", "SOL", "-USD")):
        ac, cluster, lev, sess = AssetClass.CRYPTO, "crypto_generic", 5.0, "24/7"
    elif any(k in u for k in ("XAU", "XAG", "OIL", "WTI", "GAS", "NGAS")):
        ac, cluster, lev, sess = AssetClass.COMMODITY, "commodity_generic", 10.0, "fx_sessions"
    elif len(alpha) == 6 and alpha.isalpha() and alpha[3:] in (
        "USD", "JPY", "EUR", "GBP", "CHF", "AUD", "CAD", "NZD"):
        ac, cluster, lev, sess = AssetClass.FOREX, "fx_generic", 30.0, "fx_sessions"
    else:
        ac, cluster, lev, sess = AssetClass.EQUITY, "equity_generic", 2.0, "rth"

    return PairProfile(
        symbol=symbol, asset_class=ac,
        liquidity_tier=LiquidityTier.T2,  # prudente: niente scalping aggressivo
        typical_spread_bps=max(1.0, sigma * 1e4 * 0.1),
        volatility_bucket=vol, news_sensitivity=NewsSensitivity.MID,
        correlation_cluster=cluster, tick_size=0.0, lot_size=0.0,  # 0 = nessun arrotondamento
        leverage_cap=lev, session_profile=sess,
    )

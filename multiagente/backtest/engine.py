"""BacktestEngine — replay di dati storici attraverso la pipeline di agenti.

Riusa esattamente gli stessi componenti del runtime live (router, validator,
risk, execution paper, portfolio): è il principio "stessa pipeline in backtest
e in produzione", così i risultati sono rappresentativi (ARCHITETTURA.md §10-11).

Il ``HistoricalFeed`` espone l'interfaccia ``FeedAdapter`` e avanza un indice
temporale condiviso controllato dall'engine. ``_simulate`` è il cuore riusato sia
dal backtest singolo sia dal walk-forward (con punto di congelamento OOS).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..core.types import MarketSnapshot
from ..data.market_data import FeedAdapter
from ..main import build_system
from ..portfolio.portfolio import Trade
from .metrics import BacktestMetrics, compute_metrics
from .series import Bar, synthetic_series

logger = logging.getLogger(__name__)


class HistoricalFeed(FeedAdapter):
    """Feed che fa replay di serie precaricate, una barra alla volta."""

    name = "historical"

    def __init__(self, series: dict[str, list[Bar]], window: int = 30) -> None:
        if not series:
            raise ValueError("serve almeno una serie")
        self.series = series
        self.window = window
        self.i = 0
        self.length = min(len(s) for s in series.values())

    def advance(self) -> bool:
        if self.i + 1 >= self.length:
            return False
        self.i += 1
        return True

    def fetch(self, symbol: str) -> MarketSnapshot:
        bars = self.series.get(symbol)
        if bars is None:
            raise KeyError(symbol)
        bar = bars[self.i]
        mid = bar.price
        spread = mid * 0.0001
        window = [b.price for b in bars[max(0, self.i - self.window + 1): self.i + 1]]
        return MarketSnapshot(
            symbol=symbol, ts=time.time(),
            bid=mid - spread / 2, ask=mid + spread / 2, last=mid,
            ohlcv={"1m": window}, book_imbalance=bar.imbalance,
        )


@dataclass
class SimResult:
    """Esito grezzo di una simulazione, con confini per la fase out-of-sample."""

    initial_equity: float
    equity_curve: list[float]
    trades: list[Trade]
    oos_equity_start: int | None = None  # indice in equity_curve dove inizia l'OOS
    oos_trade_start: int | None = None   # indice in trades dove iniziano i trade OOS
    steps: int = 0


def build_series(
    source: str = "synthetic",
    base_prices: dict[str, float] | None = None,
    steps: int = 300,
    seed: int = 0,
    **provider_kwargs,
) -> dict[str, list[Bar]]:
    """Costruisce le serie storiche dalla sorgente richiesta.

    ``source="yahoo"`` scarica dati reali; in caso di rete bloccata ricade sul
    sintetico con un warning (così il backtest funziona sempre).
    """
    from ..main import DEFAULT_BASE_PRICES

    base_prices = base_prices or DEFAULT_BASE_PRICES
    if source == "files":
        # storico fornito dall'utente (cartella di CSV per timeframe)
        from ..data.loaders import load_dataset

        data_dir = provider_kwargs.get("data_dir")
        if not data_dir:
            raise ValueError("source='files' richiede data_dir")
        return load_dataset(data_dir, tf=provider_kwargs.get("tf"))

    if source == "yahoo":
        try:
            from ..data.providers import ProviderError, yahoo_series

            yk = {k: v for k, v in provider_kwargs.items() if k in ("symbols", "range_", "interval", "timeout")}
            return yahoo_series(**yk)
        except ProviderError as exc:
            logger.warning("Dati reali non disponibili (%s): uso serie sintetiche", exc)

    return {
        sym: synthetic_series(px, steps, seed=seed + h)
        for h, (sym, px) in enumerate(base_prices.items())
    }


def _simulate(series: dict[str, list[Bar]], freeze_at: int | None = None) -> SimResult:
    """Esegue la pipeline su tutta la serie.

    Se ``freeze_at`` è dato, al raggiungimento di quello step congela
    l'adattamento di tutti gli agenti e marca l'inizio della fase out-of-sample.
    """
    # profili derivati dai dati per i simboli non presenti nel registro statico
    from ..data.pair_classifier import _PROFILES, derive_profile

    extra_profiles = {
        sym: derive_profile(sym, bars) for sym, bars in series.items() if sym not in _PROFILES
    }
    feed = HistoricalFeed(series)
    sys = build_system(feeds=[feed], extra_profiles=extra_profiles)
    router, validator = sys["router"], sys["validator"]
    risk, execution, portfolio = sys["risk"], sys["execution"], sys["portfolio"]
    classifier, market_data, kill = sys["classifier"], sys["market_data"], sys["kill"]
    agents = sys["agents_by_name"].values()

    symbols = [s for s in series if classifier.profile(s) is not None]
    initial_equity = portfolio.state.equity
    equity_curve = [initial_equity]
    oos_equity_start = oos_trade_start = None

    step = 0
    while feed.advance():
        step += 1
        prices: dict[str, float] = {}
        for symbol in symbols:
            snap = market_data.snapshot(symbol)
            if snap is None:
                continue
            prices[symbol] = snap.mid
            if kill.engaged:
                continue
            signals = router.route(symbol)
            if not signals:
                continue
            for vsig in validator.validate(signals, snap):
                profile = classifier.profile(symbol)
                order = risk.assess(vsig, profile)
                if order is None:
                    continue
                fill = execution.execute(order, snap)
                if fill is None:
                    continue
                risk.register_fill(order.symbol, order.meta["cluster"], order.meta["exposure_add"])
                portfolio.on_fill(fill, order, source_agent=vsig.signal.agent, regime=vsig.signal.regime)

        portfolio.mark_to_market(prices)
        risk.update_equity(portfolio.state.equity)
        equity_curve.append(portfolio.state.equity)

        # confine in/out-of-sample: congela l'adattamento per la fase OOS
        if freeze_at is not None and step == freeze_at:
            for agent in agents:
                agent.freeze()
            oos_equity_start = len(equity_curve) - 1
            oos_trade_start = len(portfolio.trades)

        # nuovo "giorno" ogni ~24 step: reset drawdown e riarmo del kill switch
        if step % 24 == 0:
            risk.start_new_day()
            if kill.engaged:
                kill.reset()

    last_prices = {s: market_data.snapshot(s).mid for s in symbols if market_data.snapshot(s)}
    portfolio.close_all(last_prices)
    equity_curve.append(portfolio.state.equity)

    return SimResult(
        initial_equity=initial_equity, equity_curve=equity_curve, trades=portfolio.trades,
        oos_equity_start=oos_equity_start, oos_trade_start=oos_trade_start, steps=step,
    )


def run_backtest(
    base_prices: dict[str, float] | None = None,
    steps: int = 300,
    seed: int = 0,
    series: dict[str, list[Bar]] | None = None,
    source: str = "synthetic",
    periods_per_year: int = 252,
) -> BacktestMetrics:
    """Esegue un backtest singolo e restituisce le metriche."""
    if series is None:
        series = build_series(source=source, base_prices=base_prices, steps=steps, seed=seed)

    res = _simulate(series)
    metrics = compute_metrics(res.initial_equity, res.equity_curve, res.trades,
                              periods_per_year=periods_per_year)
    logger.info(
        "Backtest: %d step, %d trade, rendimento %.2f%%, Sharpe %.2f, maxDD %.2f%%",
        res.steps, metrics.n_trades, metrics.total_return * 100, metrics.sharpe,
        metrics.max_drawdown * 100,
    )
    return metrics


# mappa timeframe -> orizzonte naturale (solo informativa, per il report)
TF_TO_HORIZON = {
    "1m": "scalping", "5m": "scalping", "15m": "day_trading", "30m": "day_trading",
    "1h": "day_trading", "4h": "day_trading", "1d": "investor", "1w": "investor",
}


def run_backtest_by_tf(data_dir: str) -> dict[str, BacktestMetrics]:
    """Backtest multi-timeframe: un backtest per ciascun TF presente nei dati.

    Ogni timeframe è replicato separatamente (le serie non sono fuse) e mappato
    al suo orizzonte naturale; lo Sharpe è annualizzato per TF. Ritorna
    ``{tf: BacktestMetrics}``.
    """
    from ..data.loaders import load_dataset_by_tf
    from .metrics import periods_per_year_for_tf

    by_tf = load_dataset_by_tf(data_dir)
    out: dict[str, BacktestMetrics] = {}
    for tf in sorted(by_tf, key=lambda t: list(TF_TO_HORIZON).index(t) if t in TF_TO_HORIZON else 99):
        series = by_tf[tf]
        m = run_backtest(series=series, periods_per_year=periods_per_year_for_tf(tf))
        out[tf] = m
        logger.info("[%s · %s] rend %.2f%%, Sharpe %.2f, %d trade",
                    tf, TF_TO_HORIZON.get(tf, "?"), m.total_return * 100, m.sharpe, m.n_trades)
    return out

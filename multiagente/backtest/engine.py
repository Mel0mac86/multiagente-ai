"""BacktestEngine — replay di dati storici attraverso la pipeline di agenti.

Riusa esattamente gli stessi componenti del runtime live (router, validator,
risk, execution paper, portfolio): è il principio "stessa pipeline in backtest
e in produzione", così i risultati sono rappresentativi (ARCHITETTURA.md §10).

Il ``HistoricalFeed`` espone l'interfaccia ``FeedAdapter`` e avanza un indice
temporale condiviso controllato dall'engine.
"""

from __future__ import annotations

import logging
import time

from ..core.types import MarketSnapshot
from ..data.market_data import FeedAdapter
from ..main import build_system
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
        """Avanza di una barra. Ritorna False a fine serie."""
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


def run_backtest(
    base_prices: dict[str, float] | None = None,
    steps: int = 300,
    seed: int = 0,
    series: dict[str, list[Bar]] | None = None,
) -> BacktestMetrics:
    """Esegue un backtest e restituisce le metriche.

    Se ``series`` è dato, lo usa; altrimenti genera serie sintetiche dai
    ``base_prices`` (default: paniere multi-mercato).
    """
    from ..main import DEFAULT_BASE_PRICES

    base_prices = base_prices or DEFAULT_BASE_PRICES
    if series is None:
        series = {
            sym: synthetic_series(px, steps, seed=seed + h)
            for h, (sym, px) in enumerate(base_prices.items())
        }

    feed = HistoricalFeed(series)
    sys = build_system(feeds=[feed])
    router = sys["router"]
    validator = sys["validator"]
    risk = sys["risk"]
    execution = sys["execution"]
    portfolio = sys["portfolio"]
    classifier = sys["classifier"]
    market_data = sys["market_data"]
    kill = sys["kill"]

    symbols = [s for s in series if classifier.profile(s) is not None]
    initial_equity = portfolio.state.equity
    equity_curve = [initial_equity]

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
        # reset del drawdown giornaliero ogni ~24 step (proxy di "nuovo giorno").
        # Nel backtest riarmiamo anche il kill switch a inizio giornata (in
        # produzione il reset è manuale dopo verifica).
        if step % 24 == 0:
            risk.start_new_day()
            if kill.engaged:
                kill.reset()

    # chiusura forzata a fine backtest per liberare le posizioni residue
    last_prices = {s: market_data.snapshot(s).mid for s in symbols if market_data.snapshot(s)}
    portfolio.close_all(last_prices)
    equity_curve.append(portfolio.state.equity)

    metrics = compute_metrics(initial_equity, equity_curve, portfolio.trades)
    logger.info(
        "Backtest: %d step, %d trade, rendimento %.2f%%, Sharpe %.2f, maxDD %.2f%%",
        step, metrics.n_trades, metrics.total_return * 100, metrics.sharpe, metrics.max_drawdown * 100,
    )
    return metrics

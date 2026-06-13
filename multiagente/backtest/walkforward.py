"""Walk-forward — validazione out-of-sample (ARCHITETTURA.md §11).

Per ogni fold: adatta i parametri sulla parte *in-sample* (finestra espansiva),
poi li **congela** (``StrategyAgent.freeze``) e misura la performance sulla parte
*out-of-sample* mai vista. Le metriche OOS dei fold vengono concatenate
(componendo i rendimenti) in un'unica curva equity OOS: è la stima più onesta
della tenuta del sistema, e mette alla prova l'auto-adattamento contro
l'overfitting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .engine import _simulate, build_series
from .metrics import BacktestMetrics, compute_metrics
from .series import Bar

logger = logging.getLogger(__name__)


@dataclass
class Fold:
    index: int
    train_bars: int
    test_bars: int
    metrics: BacktestMetrics


@dataclass
class WalkForwardResult:
    aggregate: BacktestMetrics       # metriche sulla curva OOS concatenata
    folds: list[Fold] = field(default_factory=list)


def run_walk_forward(
    series: dict[str, list[Bar]] | None = None,
    steps: int = 600,
    seed: int = 0,
    source: str = "synthetic",
    n_folds: int = 4,
    train_frac: float = 0.5,
) -> WalkForwardResult:
    """Esegue il walk-forward e restituisce le metriche OOS aggregate + per fold."""
    if series is None:
        series = build_series(source=source, steps=steps, seed=seed)

    length = min(len(s) for s in series.values())
    test_total_start = int(length * train_frac)
    remaining = length - test_total_start
    if n_folds < 1 or remaining < n_folds * 5:
        raise ValueError("serie troppo corta per il numero di fold richiesto")
    test_len = remaining // n_folds

    folds: list[Fold] = []
    combined_curve: list[float] = []
    combined_trades = []

    for k in range(n_folds):
        test_start = test_total_start + k * test_len
        test_end = length if k == n_folds - 1 else test_start + test_len
        # finestra espansiva: train = [0..test_start], test = (test_start..test_end]
        fold_series = {sym: bars[:test_end] for sym, bars in series.items()}

        res = _simulate(fold_series, freeze_at=test_start)
        if res.oos_equity_start is None:
            continue
        oos_equity = res.equity_curve[res.oos_equity_start:]
        oos_trades = res.trades[res.oos_trade_start:]
        if len(oos_equity) < 2:
            continue

        fm = compute_metrics(oos_equity[0], oos_equity, oos_trades)
        folds.append(Fold(index=k, train_bars=test_start, test_bars=test_end - test_start, metrics=fm))

        # concatena (componendo) la curva OOS del fold sulla curva aggregata
        base = combined_curve[-1] if combined_curve else oos_equity[0]
        f0 = oos_equity[0] or 1.0
        if not combined_curve:
            combined_curve.append(base)
        for v in oos_equity[1:]:
            combined_curve.append(base * v / f0)
        combined_trades.extend(oos_trades)

    if not combined_curve:
        raise RuntimeError("walk-forward senza dati OOS: aumenta steps o riduci n_folds")

    aggregate = compute_metrics(combined_curve[0], combined_curve, combined_trades)
    logger.info(
        "Walk-forward OOS: %d fold, rendimento %.2f%%, Sharpe %.2f, maxDD %.2f%%, %d trade",
        len(folds), aggregate.total_return * 100, aggregate.sharpe,
        aggregate.max_drawdown * 100, aggregate.n_trades,
    )
    return WalkForwardResult(aggregate=aggregate, folds=folds)

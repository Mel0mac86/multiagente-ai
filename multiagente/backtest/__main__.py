"""CLI del backtest: simulazione singola o walk-forward + report HTML.

    # backtest singolo su dati sintetici (offline)
    python -m multiagente.backtest

    # dati REALI da Yahoo Finance (nessuna API key)
    python -m multiagente.backtest --source yahoo --out report.html

    # walk-forward out-of-sample
    python -m multiagente.backtest --mode walkforward --folds 4 --steps 600

Il report è un file HTML autonomo: aprilo in Safari su iPhone (anche offline).
"""

from __future__ import annotations

import argparse
import logging

from .engine import build_series, run_backtest
from .report import write_report, write_walkforward_report
from .walkforward import run_walk_forward


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest del sistema multi-agente")
    p.add_argument("--mode", choices=["single", "walkforward"], default="single")
    p.add_argument("--source", choices=["synthetic", "yahoo", "files"], default="synthetic",
                   help="dati: sintetica (offline), Yahoo (reale), files (tuoi CSV)")
    p.add_argument("--data-dir", help="cartella dei tuoi CSV (con --source files)")
    p.add_argument("--tf", help="timeframe da caricare, es. 1h, 15m, 1d (con --source files)")
    p.add_argument("--steps", type=int, default=300, help="barre (sorgente sintetica)")
    p.add_argument("--seed", type=int, default=0, help="seed (sorgente sintetica)")
    p.add_argument("--folds", type=int, default=4, help="numero di fold (walk-forward)")
    p.add_argument("--train-frac", type=float, default=0.5, help="quota in-sample iniziale")
    p.add_argument("--range", default="1y", help="periodo Yahoo (es. 6mo, 1y, 2y)")
    p.add_argument("--interval", default="1d", help="intervallo Yahoo (es. 1d, 1h)")
    p.add_argument("--out", default="report.html", help="percorso del report HTML")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Per Yahoo/files costruiamo le serie qui (così range/interval/data-dir valgono).
    series = None
    if args.source == "yahoo":
        series = build_series(source="yahoo", steps=args.steps, seed=args.seed,
                              range_=args.range, interval=args.interval)
    elif args.source == "files":
        series = build_series(source="files", data_dir=args.data_dir, tf=args.tf)

    if args.mode == "walkforward":
        result = run_walk_forward(series=series, steps=args.steps, seed=args.seed,
                                  source=args.source, n_folds=args.folds, train_frac=args.train_frac)
        path = write_walkforward_report(result, args.out)
        m = result.aggregate
        print(f"\nWalk-forward OOS · report: {path}")
        print(f"Rend. OOS: {m.total_return*100:.2f}%  |  Sharpe: {m.sharpe:.2f}  "
              f"|  Max DD: {m.max_drawdown*100:.2f}%  |  Trade: {m.n_trades}  |  Fold: {len(result.folds)}")
        return

    m = run_backtest(series=series, steps=args.steps, seed=args.seed, source=args.source)
    path = write_report(m, args.out)
    print(f"\nBacktest · report: {path}")
    print(f"Rendimento: {m.total_return*100:.2f}%  |  Sharpe: {m.sharpe:.2f}  "
          f"|  Max DD: {m.max_drawdown*100:.2f}%  |  Trade: {m.n_trades}  "
          f"|  Hit-rate: {m.hit_rate*100:.1f}%")


if __name__ == "__main__":
    main()

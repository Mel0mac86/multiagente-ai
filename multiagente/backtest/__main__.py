"""CLI del backtest: esegue una simulazione e scrive un report HTML.

    python -m multiagente.backtest                 # 300 step, report.html
    python -m multiagente.backtest --steps 500 --out report.html --seed 1

Il report è un file HTML autonomo: aprilo in Safari su iPhone (anche offline).
"""

from __future__ import annotations

import argparse
import logging

from .engine import run_backtest
from .report import write_report


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest del sistema multi-agente")
    p.add_argument("--steps", type=int, default=300, help="numero di barre storiche")
    p.add_argument("--seed", type=int, default=0, help="seed per le serie sintetiche")
    p.add_argument("--out", default="report.html", help="percorso del report HTML")
    p.add_argument("--quiet", action="store_true", help="meno log")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    metrics = run_backtest(steps=args.steps, seed=args.seed)
    path = write_report(metrics, args.out)

    print(f"\nReport scritto in: {path}")
    print(f"Rendimento: {metrics.total_return * 100:.2f}%  |  Sharpe: {metrics.sharpe:.2f}  "
          f"|  Max DD: {metrics.max_drawdown * 100:.2f}%  |  Trade: {metrics.n_trades}  "
          f"|  Hit-rate: {metrics.hit_rate * 100:.1f}%")


if __name__ == "__main__":
    main()

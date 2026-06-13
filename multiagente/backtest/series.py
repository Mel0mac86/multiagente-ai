"""Generazione/caricamento di serie storiche per il backtest.

Due fonti:
  * ``synthetic_series``: random walk a segmenti di regime (trend/range/shock),
    puro Python e deterministico (seed) — utile per demo offline anche su iPhone.
  * ``load_csv_series``: carica OHLC da CSV (colonna ``close`` minima).

Ogni serie è una lista di ``Bar`` con prezzo e book imbalance (proxy del flusso).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass


@dataclass
class Bar:
    price: float
    imbalance: float  # -1..+1, proxy dello sbilanciamento del book / momentum


def synthetic_series(base_price: float, n: int, vol: float = 0.006, seed: int = 0) -> list[Bar]:
    """Random walk a segmenti di regime.

    Alterna fasi di trend (drift positivo/negativo, imbalance coerente), fasi di
    range (drift ~0) e occasionali shock di volatilità.
    """
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = base_price
    i = 0
    while i < n:
        phase = rng.choice(["trend_up", "trend_down", "range", "range", "shock"])
        length = rng.randint(15, 40)
        for _ in range(length):
            if i >= n:
                break
            if phase == "trend_up":
                drift, imb = vol * 0.4, rng.uniform(0.3, 0.9)
            elif phase == "trend_down":
                drift, imb = -vol * 0.4, rng.uniform(-0.9, -0.3)
            elif phase == "shock":
                drift, imb = 0.0, rng.uniform(-1, 1)
            else:  # range
                drift, imb = 0.0, rng.uniform(-0.25, 0.25)
            shock_vol = vol * (3.0 if phase == "shock" else 1.0)
            price *= 1 + drift + rng.gauss(0, shock_vol)
            price = max(price, base_price * 0.2)  # evita derive a zero
            bars.append(Bar(price=price, imbalance=max(-1.0, min(1.0, imb))))
            i += 1
    return bars


def load_csv_series(path: str, price_col: str = "close") -> list[Bar]:
    """Carica una serie da CSV. L'imbalance è derivata dalla variazione di prezzo."""
    bars: list[Bar] = []
    prev: float | None = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            price = float(row[price_col])
            if prev is None:
                imb = 0.0
            else:
                chg = (price - prev) / prev if prev else 0.0
                imb = max(-1.0, min(1.0, chg * 200))  # scala la variazione in [-1,1]
            bars.append(Bar(price=price, imbalance=imb))
            prev = price
    return bars

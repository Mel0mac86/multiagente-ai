"""Caricatori per storici reali forniti dall'utente (CSV multi-formato).

Pensato per i file che si esportano da TradingView, MetaTrader (MT4/MT5),
Dukascopy o app mobile, già divisi per timeframe. Rileva in automatico:
  * delimitatore (``,`` ``;`` ``\\t``) e presenza dell'header (csv.Sniffer);
  * nomi di colonna comuni (anche in italiano: chiusura/apertura/massimo/minimo);
  * formato MetaTrader senza header (DATE,TIME,O,H,L,C,VOL) via posizione.

Convenzione a cartelle (consigliata per più strumenti/timeframe):

    dati/
      BTCUSDT_1h.csv
      EURUSD_15m.csv
      AAPL/1d.csv          # oppure sottocartella per simbolo
      XAUUSD/1h.csv

``load_dataset(dir, tf="1h")`` carica tutti i file di quel timeframe e mappa il
nome file → simbolo interno. I simboli non presenti nel registro dei profili
ottengono un profilo *derivato dai dati* (volatilità/spread stimati), così
funzionano comunque.
"""

from __future__ import annotations

import csv
import logging
import os
import re

from ..backtest.series import Bar

logger = logging.getLogger(__name__)

# Nomi di colonna accettati (lowercase). Ordine = priorità.
_COL = {
    "close": ["close", "close_price", "adj close", "adj_close", "c", "chiusura", "ultimo", "price"],
    "open": ["open", "o", "apertura"],
    "high": ["high", "h", "massimo", "max"],
    "low": ["low", "l", "minimo", "min"],
    "volume": ["volume", "vol", "v", "quantità"],
}

# Mappa filename → simbolo interno del sistema (estendibile).
_SYMBOL_ALIASES = {
    "BTCUSDT": "BTC/USDT", "BTCUSD": "BTC/USDT", "BTC": "BTC/USDT",
    "ETHUSDT": "ETH/USDT", "ETHUSD": "ETH/USDT", "ETH": "ETH/USDT",
    "EURUSD": "EUR/USD", "USDTRY": "USD/TRY",
    "XAUUSD": "XAU/USD", "GOLD": "XAU/USD", "WTI": "WTI", "USOIL": "WTI", "CL": "WTI",
    "SPX": "SPX", "SPX500": "SPX", "US500": "SPX", "AAPL": "AAPL",
    "USDTUSDC": "USDT/USDC",
}

_TF_RE = re.compile(r"(?i)(?:^|[_\-\.])(\d+\s*(?:m|min|h|hour|d|day|w|week)|m\d+|h\d+|daily|weekly)(?:$|[_\-\.])")


def _to_float(s: str) -> float | None:
    s = s.strip().replace(" ", "")
    if not s:
        return None
    # gestisce sia 1,234.56 sia 1.234,56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def load_ohlcv_file(path: str) -> list[Bar]:
    """Carica un singolo file OHLCV in una serie di ``Bar`` (con autodetection)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = True
        rows = list(csv.reader(f, dialect))

    rows = [r for r in rows if r and any(c.strip() for c in r)]
    if not rows:
        raise ValueError(f"file vuoto: {path}")

    closes: list[float] = []
    if has_header:
        header = [h.strip().lower() for h in rows[0]]
        idx = _resolve_columns(header)
        if idx.get("close") is not None:
            ci = idx["close"]
            for r in rows[1:]:
                if ci < len(r) and (v := _to_float(r[ci])) is not None:
                    closes.append(v)
        else:
            closes = _positional_closes(rows[1:])
    else:
        closes = _positional_closes(rows)

    if len(closes) < 2:
        raise ValueError(f"meno di 2 prezzi validi in {path}")
    return _closes_to_bars(closes)


def _resolve_columns(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for key, names in _COL.items():
        for name in names:
            if name in header:
                idx[key] = header.index(name)
                break
    return idx


def _positional_closes(rows: list[list[str]]) -> list[float]:
    """Formato senza header (es. MetaTrader): close = 4° valore numerico OHLC."""
    out: list[float] = []
    for r in rows:
        nums = [v for v in (_to_float(c) for c in r) if v is not None]
        if len(nums) >= 4:
            out.append(nums[3])   # open, high, low, CLOSE, [volume]
        elif nums:
            out.append(nums[-1])
    return out


def _closes_to_bars(closes: list[float]) -> list[Bar]:
    bars: list[Bar] = []
    prev: float | None = None
    for price in closes:
        if prev is None or prev == 0:
            imb = 0.0
        else:
            imb = max(-1.0, min(1.0, (price - prev) / prev * 200))
        bars.append(Bar(price=price, imbalance=imb))
        prev = price
    return bars


def _norm_tf(raw: str) -> str:
    raw = raw.lower().replace(" ", "")
    raw = {"daily": "1d", "weekly": "1w"}.get(raw, raw)
    m = re.match(r"(?:([a-z])(\d+)|(\d+)([a-z]+))", raw)
    if not m:
        return raw
    if m.group(1):           # es. "h1" -> "1h"
        unit, num = m.group(1), m.group(2)
    else:                    # es. "15min" -> "15m"
        num, unit = m.group(3), m.group(4)[0]
    return f"{int(num)}{unit}"


def _symbol_from_name(name: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return _SYMBOL_ALIASES.get(key, name.upper())


def load_dataset(data_dir: str, tf: str | None = None) -> dict[str, list[Bar]]:
    """Carica una cartella di storici, filtrando per timeframe se indicato.

    Riconosce sia ``SIMBOLO_TF.csv`` sia ``SIMBOLO/TF.csv``. Ritorna
    ``{simbolo_interno: [Bar, ...]}``.
    """
    want = _norm_tf(tf) if tf else None
    out: dict[str, list[Bar]] = {}
    for root, _dirs, files in os.walk(data_dir):
        for fn in files:
            if not fn.lower().endswith((".csv", ".txt", ".tsv")):
                continue
            path = os.path.join(root, fn)
            stem = os.path.splitext(fn)[0]
            # timeframe dal nome file, dalla sottocartella o dal nome file stesso
            tf_match = _TF_RE.search(fn) or _TF_RE.search(stem)
            file_tf = _norm_tf(tf_match.group(1)) if tf_match else _norm_tf(stem)
            sub = os.path.basename(root)
            file_tf = _norm_tf(sub) if (want and _norm_tf(sub) == want) else file_tf
            if want and file_tf != want and _norm_tf(sub) != want:
                continue
            # simbolo: parte del filename senza il pezzo tf, oppure dalla cartella
            base = _TF_RE.sub("", stem).strip("_-. ")
            symbol = _symbol_from_name(base or sub)
            try:
                bars = load_ohlcv_file(path)
            except (ValueError, OSError) as exc:
                logger.warning("Salto %s: %s", path, exc)
                continue
            out[symbol] = bars
            logger.info("Caricato %s (%s) <- %s [%d barre]", symbol, file_tf, fn, len(bars))
    if not out:
        raise ValueError(f"nessun file caricato da {data_dir} (tf={tf})")
    return out

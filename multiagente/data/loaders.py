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

# MT4/MT5: il periodo nel nome file è in MINUTI (es. EURUSD60 = H1, XAUUSD1440 = D1).
_MT4_PERIODS = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h",
                "240": "4h", "1440": "1d", "10080": "1w", "43200": "1mo"}
_MT4_NAME_RE = re.compile(r"^([A-Za-z]{3,})(\d{1,5})$")


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


# MetaTrader 5: suffisso timeframe nel nome (AAPL_H1, XAU_MN1, AUDCAD_D1).
_MT5_TF = {
    "m1": "1m", "m5": "5m", "m15": "15m", "m30": "30m",
    "h1": "1h", "h4": "4h", "d1": "1d", "w1": "1w", "mn1": "1mo", "mn": "1mo",
}


def _parse_name(stem: str) -> tuple[str, str | None]:
    """Estrae (simbolo_grezzo, timeframe) dal nome file (senza estensione).

    Gestisce: suffisso MT5 ``SIMBOLO_H1``/``_M15``/``_D1``/``_MN1``;
    ``SIMBOLO_TF`` con unità (``_1h``, ``_15m``); convenzione MT4 concatenata
    ``SIMBOLO<minuti>`` (es. EURUSD60). Per non spezzare gli indici con numeri
    (US30, GER40), la parte alfabetica deve avere ≥3 lettere e il numero finale
    essere un periodo MT4 valido.
    """
    # 1) suffisso MT5 dopo separatore (caso più comune negli export MT5)
    parts = re.split(r"[_\-.]", stem)
    if len(parts) >= 2 and parts[-1].lower() in _MT5_TF:
        return "_".join(parts[:-1]), _MT5_TF[parts[-1].lower()]
    # 2) timeframe con unità esplicita (_1h, _15m, 1d...)
    m = _TF_RE.search(stem)
    if m:
        tf = _norm_tf(m.group(1))
        sym = _TF_RE.sub("", stem).strip("_-. ")
        return sym, tf
    # 3) separatore + minuti MT4 (es. US30_60 -> US30, 1h)
    sep = re.match(r"^(.*?)[_\-.](\d{1,5})$", stem)
    if sep and sep.group(2) in _MT4_PERIODS:
        return sep.group(1), _MT4_PERIODS[sep.group(2)]
    # 4) concatenato SIMBOLO+minuti (es. EURUSD60 -> EUR/USD, 1h)
    mm = _MT4_NAME_RE.match(stem)
    if mm and mm.group(2) in _MT4_PERIODS:
        return mm.group(1), _MT4_PERIODS[mm.group(2)]
    return stem, None


def load_dataset(data_dir: str, tf: str | None = None) -> dict[str, list[Bar]]:
    """Carica una cartella di storici, filtrando per timeframe se indicato.

    ``data_dir`` può essere una cartella **oppure un file .zip** (comodo per
    caricare tutto in una volta dall'iPhone): lo zip viene estratto in una
    cartella temporanea e scansionato. Riconosce sia ``SIMBOLO_TF.csv`` sia
    ``SIMBOLO/TF.csv``. Ritorna ``{simbolo_interno: [Bar, ...]}``.
    """
    data_dir = _maybe_unzip(data_dir)
    want = _norm_tf(tf) if tf else None
    out: dict[str, list[Bar]] = {}
    for symbol, file_tf, bars, fn in _iter_dataset(data_dir):
        if want is not None and file_tf != want:
            continue
        out[symbol] = bars
        logger.info("Caricato %s (%s) <- %s [%d barre]", symbol, file_tf, fn, len(bars))
    if not out:
        raise ValueError(f"nessun file caricato da {data_dir} (tf={tf})")
    return out


def load_dataset_by_tf(data_dir: str) -> dict[str, dict[str, list[Bar]]]:
    """Carica tutto raggruppando per timeframe: ``{tf: {simbolo: [Bar, ...]}}``.

    Evita la collisione di simboli quando lo stesso strumento è presente su più
    timeframe (es. BTC/USDT su 15m e 1h). Usato dal backtest multi-timeframe.
    """
    data_dir = _maybe_unzip(data_dir)
    out: dict[str, dict[str, list[Bar]]] = {}
    for symbol, file_tf, bars, fn in _iter_dataset(data_dir):
        out.setdefault(file_tf, {})[symbol] = bars
        logger.info("Caricato %s (%s) <- %s [%d barre]", symbol, file_tf, fn, len(bars))
    if not out:
        raise ValueError(f"nessun file caricato da {data_dir}")
    return out


def _maybe_unzip(data_dir: str) -> str:
    import shutil
    import tempfile
    import zipfile

    data_dir = _maybe_download(data_dir)

    if os.path.isfile(data_dir) and zipfile.is_zipfile(data_dir):
        tmp = tempfile.mkdtemp(prefix="storico_")
        with zipfile.ZipFile(data_dir) as zf:
            zf.extractall(tmp)
        logger.info("ZIP estratto in %s", tmp)
        return tmp
    # singolo CSV: lo metto in una cartella temporanea così os.walk funziona
    if os.path.isfile(data_dir):
        tmp = tempfile.mkdtemp(prefix="storico_")
        shutil.copy(data_dir, tmp)
        return tmp
    return data_dir


def _maybe_download(path_or_url: str) -> str:
    """Se è un URL http(s), scarica in una cartella temporanea e ritorna il path.

    Normalizza i link Dropbox (`?dl=0` → download diretto). Per altri servizi usa
    un link di **download diretto** al file (zip o csv).
    """
    if not str(path_or_url).lower().startswith(("http://", "https://")):
        return path_or_url

    import tempfile
    import urllib.parse
    import urllib.request

    url = path_or_url
    if "dropbox.com" in url:
        url = url.replace("dl=0", "dl=1")
        url = url.replace("www.dropbox.com", "dl.dropboxusercontent.com")

    name = os.path.basename(urllib.parse.urlparse(url).path) or "download"
    if not name.lower().endswith((".zip", ".csv", ".txt", ".tsv")):
        name += ".zip"  # assume archivio se l'estensione non è chiara
    dest = os.path.join(tempfile.mkdtemp(prefix="dl_"), name)

    logger.info("Scarico i dati da %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "multiagente-ai/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310
        f.write(r.read())
    logger.info("Scaricato in %s (%d byte)", dest, os.path.getsize(dest))
    return dest


def _iter_dataset(data_dir: str):
    """Genera ``(simbolo, timeframe, bars, filename)`` per ogni file valido."""
    for root, _dirs, files in os.walk(data_dir):
        for fn in files:
            if fn.startswith(".") or fn.startswith("__"):
                continue  # ignora file nascosti / __MACOSX
            if not fn.lower().endswith((".csv", ".txt", ".tsv")):
                continue
            path = os.path.join(root, fn)
            stem = os.path.splitext(fn)[0]
            sub = os.path.basename(root)
            sym_raw, file_tf = _parse_name(stem)
            if file_tf is None and sub:
                file_tf = _norm_tf(sub)
            symbol = _symbol_from_name(sym_raw or sub)
            file_tf = file_tf or "?"
            try:
                bars = load_ohlcv_file(path)
            except (ValueError, OSError) as exc:
                logger.warning("Salto %s: %s", path, exc)
                continue
            yield symbol, file_tf, bars, fn

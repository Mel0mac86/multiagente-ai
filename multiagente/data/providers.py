"""Provider di dati storici reali — Yahoo Finance (nessuna API key).

Usa solo la libreria standard (``urllib``) per scaricare OHLCV dall'endpoint
chart pubblico di Yahoo, che copre tutti e 4 i mercati del sistema:

    crypto    BTC/USDT -> BTC-USD       indici     SPX -> ^GSPC
    forex     EUR/USD  -> EURUSD=X       commodity  XAU/USD -> GC=F, WTI -> CL=F
    azioni    AAPL     -> AAPL

In caso di rete non disponibile/bloccata solleva ``ProviderError``: il chiamante
(CLI/engine) ricade automaticamente sulle serie sintetiche.

Estensione naturale: un ``BinanceProvider`` per klines crypto ad alta frequenza
o l'adapter del proprio broker, mantenendo la stessa firma ``series(...)``.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .pair_classifier import _PROFILES  # registro dei simboli noti
from ..backtest.series import Bar

logger = logging.getLogger(__name__)

# Mappa: simbolo interno -> ticker Yahoo. USDT/USDC non ha equivalente: si omette
# (ricadrà sul sintetico se richiesto).
YAHOO_SYMBOLS: dict[str, str] = {
    "BTC/USDT": "BTC-USD",
    "ETH/USDT": "ETH-USD",
    "EUR/USD": "EURUSD=X",
    "USD/TRY": "TRY=X",
    "AAPL": "AAPL",
    "SPX": "^GSPC",
    "XAU/USD": "GC=F",
    "WTI": "CL=F",
}

_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


class ProviderError(RuntimeError):
    """Rete non disponibile, simbolo non mappato o risposta malformata."""


def _fetch_closes(ticker: str, range_: str, interval: str, timeout: float) -> list[float]:
    url = f"{_BASE}{urllib.parse.quote(ticker)}?range={range_}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "multiagente-ai/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - host fisso
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"rete non disponibile per {ticker}: {exc}") from exc
    try:
        result = payload["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"risposta Yahoo malformata per {ticker}") from exc
    # rimuove i buchi (None) propagando l'ultimo valore valido
    cleaned: list[float] = []
    last = None
    for c in closes:
        if c is None:
            if last is not None:
                cleaned.append(last)
        else:
            cleaned.append(float(c))
            last = float(c)
    if len(cleaned) < 2:
        raise ProviderError(f"serie troppo corta per {ticker}")
    return cleaned


def _closes_to_bars(closes: list[float]) -> list[Bar]:
    bars: list[Bar] = []
    prev: float | None = None
    for price in closes:
        if prev is None or prev == 0:
            imb = 0.0
        else:
            chg = (price - prev) / prev
            imb = max(-1.0, min(1.0, chg * 200))  # scala la variazione in [-1,1]
        bars.append(Bar(price=price, imbalance=imb))
        prev = price
    return bars


def yahoo_series(
    symbols: list[str] | None = None,
    range_: str = "1y",
    interval: str = "1d",
    timeout: float = 10.0,
) -> dict[str, list[Bar]]:
    """Scarica le serie reali e le converte in ``Bar`` per il backtest.

    Solleva ``ProviderError`` se nessun simbolo è scaricabile (rete bloccata).
    Salta i simboli senza mapping Yahoo (es. USDT/USDC).
    """
    symbols = symbols or [s for s in _PROFILES if s in YAHOO_SYMBOLS]
    out: dict[str, list[Bar]] = {}
    errors: list[str] = []
    for sym in symbols:
        ticker = YAHOO_SYMBOLS.get(sym)
        if ticker is None:
            continue
        try:
            closes = _fetch_closes(ticker, range_, interval, timeout)
        except ProviderError as exc:
            errors.append(str(exc))
            continue
        out[sym] = _closes_to_bars(closes)
        logger.info("Yahoo: %s (%s) -> %d barre", sym, ticker, len(out[sym]))
    if not out:
        raise ProviderError("nessuna serie scaricabile: " + "; ".join(errors[:3]))
    return out

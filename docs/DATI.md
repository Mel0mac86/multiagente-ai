# Usare i tuoi storici

Il sistema carica **CSV OHLCV già divisi per timeframe**. Il loader
(`multiagente/data/loaders.py`) rileva da solo delimitatore, header e nomi di
colonna, quindi nella maggior parte dei casi **non devi convertire nulla**.

## Formati accettati

Funzionano gli export tipici di TradingView, MetaTrader (MT4/MT5), Dukascopy e
app mobile. Il loader riconosce:

- **Delimitatori**: virgola `,`, punto e virgola `;`, tab.
- **Con header** — nomi colonna (anche italiani):
  `close`/`chiusura`/`ultimo`/`price`, `open`/`apertura`, `high`/`massimo`,
  `low`/`minimo`, `volume`. Basta che ci sia almeno la colonna di **chiusura**.
- **Senza header** (stile MetaTrader): `DATE,TIME,OPEN,HIGH,LOW,CLOSE,VOL` o
  `DATE,OPEN,HIGH,LOW,CLOSE,VOL` — la chiusura è presa per posizione (4º numero OHLC).
- **Decimali** sia `1.234,56` sia `1,234.56`.

Esempi validi:

```
# TradingView
time,open,high,low,close,Volume
2024-01-01T00:00,65000,65120,64880,65010,42

# MetaTrader (senza header, ';')
2024.01.01;00:00;1.08000;1.08050;1.07950;1.08010;37

# Header in italiano
data,apertura,massimo,minimo,chiusura
2024-01-01 00:00,2400.0,2403.1,2399.2,2401.8
```

## MetaTrader 4 (export "History Center")

I CSV di MT4 sono già supportati **così come sono**: nessuna intestazione,
separati da virgola, data `YYYY.MM.DD`, righe `DATE,TIME,OPEN,HIGH,LOW,CLOSE,VOL`.

MT4 nomina i file con il **periodo in minuti**: il loader lo converte da solo.

| File MT4 | Periodo | Interpretato come |
|---|---|---|
| `EURUSD1.csv` | M1 | EUR/USD · `1m` |
| `EURUSD15.csv` | M15 | EUR/USD · `15m` |
| `EURUSD60.csv` | H1 | EUR/USD · `1h` |
| `XAUUSD240.csv` | H4 | XAU/USD · `4h` |
| `GBPUSD1440.csv` | D1 | GBP/USD · `1d` |

Gli indici con numeri nel nome (`US30`, `GER40`, `SP500`) non vengono spezzati;
se vuoi indicarne il periodo usa l'underscore: `US30_60.csv` → US30 · `1h`.

## Convenzione delle cartelle (consigliata)

Metti i file in una cartella e nomina così (il loader estrae **simbolo** e
**timeframe** dal nome o dalla sottocartella):

```
dati/
  BTCUSDT_1h.csv      EURUSD_15m.csv     XAUUSD_1d.csv
  AAPL/1h.csv         SPX/1d.csv          # oppure sottocartella per simbolo
```

Timeframe riconosciuti: `1m 5m 15m 30m 1h 4h 1d 1w` (e varianti `H1`, `15min`,
`daily`…). I nomi file vengono mappati ai simboli interni
(`BTCUSDT→BTC/USDT`, `EURUSD→EUR/USD`, `XAUUSD→XAU/USD`, `US500/SPX500→SPX`, …);
gli alias sono in `loaders.py:_SYMBOL_ALIASES` e si estendono facilmente.

I simboli **non** presenti nel registro dei profili ricevono un **profilo
derivato dai dati** (volatilità/spread stimati, liquidità prudente T2): funzionano
subito, anche se non li ho mappati a mano.

## Eseguire il backtest sui tuoi dati

```bash
# un timeframe (consigliato per iniziare)
python -m multiagente.backtest --source files --data-dir ./dati --tf 1h

# walk-forward out-of-sample sugli stessi dati
python -m multiagente.backtest --mode walkforward --source files --data-dir ./dati --tf 1h --folds 4
```

Il timeframe va scelto in base all'orizzonte che vuoi testare:
`1m`–`5m` per lo scalping, `15m`–`1h` per il day trading, `1d`–`1w` per l'investor.

## Come passare i file dall'iPhone

**Metodo consigliato — un solo ZIP, caricato in chat (nessun PC):**

1. Nell'app **File** dell'iPhone metti gli export nella cartella `dati/` con i
   nomi `SIMBOLO_TF.csv` (vedi sopra).
2. Tieni premuto sulla cartella → **Comprimi**: ottieni `dati.zip`.
3. **Allega lo `.zip` qui in chat.** Il backtest gira nel cloud: lo eseguo io e
   ti rimando il `report.html` (da aprire in Safari). Non ti serve installare nulla.

Il loader accetta direttamente lo zip:

```bash
python -m multiagente.backtest --source files --data-dir dati.zip --tf 1h
```

**Alternative** (se preferisci eseguire tu):

- **Sull'iPhone** con **a-Shell**/**Pythonista**: punta `--data-dir` alla cartella
  (o allo zip) nell'app File.
- **Su PC/Mac**: copia la cartella via AirDrop/iCloud e lancia lo stesso comando.

> Se i tuoi file hanno un formato particolare che il loader non riconosce,
> mandami **2-3 righe di esempio** (header + un paio di righe dati) e aggiungo il
> parser in pochi minuti.

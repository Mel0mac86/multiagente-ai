# multiagente-ai

Sistema **AI multi-agente per il trading** con approccio **ibrido**: agenti di
ragionamento basati su **Claude** (analisi news/sentiment, arbitraggio dei
segnali, supervisione) combinati con **modelli quantitativi/ML classici**
(segnali tecnici, stima del rischio, regime detection).

Il sistema classifica gli agenti su tre orizzonti operativi —
**Scalping**, **Day Trading**, **Investor** — e classifica gli asset in
**profili di coppia** (per non generalizzare il comportamento) su 4 mercati:
**crypto, forex, azioni/indici, materie prime**.

> ⚠️ **Disclaimer.** Questo repository è materiale didattico/architetturale.
> Lo scaffold gira in modalità *paper/simulazione* di default e **non** invia
> ordini reali. Il trading comporta rischio di perdita del capitale.

## Documentazione

- **[docs/ARCHITETTURA.md](docs/ARCHITETTURA.md)** — il design completo:
  tassonomia degli agenti, classificazione delle coppie, ruoli/input/output/logica,
  routing e validazione, gestione dei guasti, auto-adattamento e collaborazione.

## Struttura del codice

```
multiagente/
├── config.py              # configurazione globale + feature flags
├── core/
│   ├── types.py           # enum e dataclass condivise (segnali, profili, ordini)
│   ├── messaging.py       # message bus pub/sub + blackboard condivisa
│   ├── agent.py           # BaseAgent astratto + mixin di auto-adattamento
│   └── faults.py          # circuit breaker, retry, health monitor, kill switch
├── llm/
│   └── claude_client.py   # wrapper Claude (tool use, adaptive thinking, fallback)
├── data/
│   ├── market_data.py     # MarketDataAgent + adapter dei feed (failover)
│   ├── pair_classifier.py # PairClassifierAgent + profili di coppia
│   └── regime.py          # RegimeDetectorAgent (trend/range/volatile/news)
├── agents/
│   ├── scalping.py        # desk scalping
│   ├── day_trading.py     # desk day trading
│   ├── investor.py        # desk investor
│   └── sentiment.py       # NewsSentimentAgent (LLM)
├── risk/
│   └── risk_manager.py    # limiti, esposizione, correlazione, position sizing
├── orchestrator/
│   ├── router.py          # instradamento task → desk/agenti
│   └── validator.py       # validazione multi-livello dei segnali
├── execution/
│   └── execution.py       # ExecutionAgent + broker adapter (paper/live)
├── portfolio/
│   └── portfolio.py       # PnL, performance, loop di feedback per l'adattamento
├── backtest/
│   ├── series.py          # serie storiche (sintetiche seeded o da CSV)
│   ├── metrics.py         # Sharpe, max drawdown, profit factor, hit-rate…
│   ├── engine.py          # replay storico sulla STESSA pipeline di agenti
│   ├── report.py          # report HTML autonomo e mobile-first
│   └── __main__.py        # CLI: python -m multiagente.backtest
├── web/
│   └── app.py             # dashboard FastAPI opzionale (interattiva)
└── main.py                # cablaggio del sistema + loop demo
```

## Backtest

Il backtest fa **replay di dati storici attraverso la stessa identica pipeline**
del runtime live (router → validator → risk → execution → portfolio): nessuna
logica separata, quindi i risultati sono rappresentativi. Calcola rendimento,
**Sharpe**, **max drawdown**, **profit factor**, **hit-rate** — complessivi e
scomposti **per agente e per regime**, alimentando lo stesso loop di
auto-adattamento descritto in `docs/ARCHITETTURA.md` §9.

```bash
python -m multiagente.backtest                          # sintetico, 300 step
python -m multiagente.backtest --source yahoo            # DATI REALI (Yahoo, no key)
python -m multiagente.backtest --source files --data-dir ./dati --tf 1h   # I TUOI CSV
python -m multiagente.backtest --mode walkforward --folds 4 --steps 600
```

**I tuoi storici (consigliato).** Se hai già i dati divisi per timeframe, usali
direttamente: `--source files --data-dir <cartella> --tf 1h`. Il loader
riconosce da solo i formati comuni (TradingView, MetaTrader/MT4-5, Dukascopy,
header in italiano) e mappa i nomi file ai simboli. **Vedi
[docs/DATI.md](docs/DATI.md)** per formati, convenzione delle cartelle e come
trasferire i file dall'iPhone.

**Dati reali (Yahoo Finance, nessuna API key).** `--source yahoo` scarica OHLCV
reali per tutti e 4 i mercati (crypto `BTC-USD`, forex `EURUSD=X`, indici
`^GSPC`, commodities `GC=F`/`CL=F`, azioni `AAPL`) via `urllib`. Opzioni
`--range 1y --interval 1d`. Se la rete è bloccata, ricade in automatico sul
sintetico. Provider in `multiagente/data/providers.py` (estendibile a Binance o
al proprio broker); in alternativa CSV con `series.py:load_csv_series`.

**Walk-forward (out-of-sample).** `--mode walkforward` divide la storia in fold:
su ciascuno adatta i parametri *in-sample*, li **congela**, poi misura la
performance *out-of-sample* mai vista, e concatena i risultati OOS. È la stima
più onesta della tenuta del sistema (mette alla prova l'auto-adattamento contro
l'overfitting).

## Uso su iPhone

Due modi, dal più semplice:

1. **Report HTML autonomo (consigliato, niente server).** `python -m
   multiagente.backtest` genera `report.html`: un singolo file responsive (CSS
   e grafico SVG inline, zero dipendenze). Salvalo nell'app **File** o invialo a
   te stesso e aprilo in **Safari** — funziona anche offline.
2. **PWA installabile (dashboard interattiva).** Avvia il server su un
   PC/Mac/VPS e aprilo da Safari sull'iPhone:
   ```bash
   pip install fastapi uvicorn
   uvicorn multiagente.web.app:app --host 0.0.0.0 --port 8000
   ```
   Visita `http://<ip-del-pc>:8000` (stessa rete Wi-Fi), poi **Condividi →
   "Aggiungi alla schermata Home"**: parte a tutto schermo come un'app
   (manifest + service worker + icone). Pulsanti per scegliere
   modalità (backtest / walk-forward), sorgente (sintetica / Yahoo), step, seed
   e numero di fold. Endpoint JSON: `/api/backtest`.

   Per eseguire *tutto* sul telefono (senza un altro PC) usa app come **a-Shell**
   o **Pythonista**: il backtest è puro Python e non richiede dipendenze esterne
   (FastAPI serve solo per la dashboard).

## Avvio rapido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # inserisci ANTHROPIC_API_KEY (opzionale in paper mode)
python -m multiagente.main    # esegue il loop demo in modalità simulazione
```

Senza `ANTHROPIC_API_KEY` gli agenti LLM usano un fallback euristico locale, così
lo scaffold resta eseguibile end-to-end anche offline.

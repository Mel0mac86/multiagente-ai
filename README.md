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
└── main.py                # cablaggio del sistema + loop demo
```

## Avvio rapido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # inserisci ANTHROPIC_API_KEY (opzionale in paper mode)
python -m multiagente.main    # esegue il loop demo in modalità simulazione
```

Senza `ANTHROPIC_API_KEY` gli agenti LLM usano un fallback euristico locale, così
lo scaffold resta eseguibile end-to-end anche offline.

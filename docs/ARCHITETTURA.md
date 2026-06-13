# Architettura del sistema AI multi-agente per il trading

Documento di design. Definisce la tassonomia degli agenti, la classificazione
degli asset, ruoli/input/output/logica di ogni agente, l'instradamento e la
validazione delle attività, la gestione dei guasti, l'auto-adattamento e la
collaborazione tra agenti.

Approccio **ibrido**: gli agenti di *ragionamento* (news, sentiment, supervisione,
arbitraggio dei segnali, narrazione del rischio) usano **Claude** (`claude-opus-4-8`,
adaptive thinking, tool use); gli agenti di *segnale e rischio* usano **modelli
quantitativi/ML** deterministici e veloci. Il principio: l'LLM ragiona dove
serve giudizio e contesto; il quant calcola dove servono latenza e ripetibilità.

---

## 1. Principi di progetto

1. **Niente generalizzazione cieca.** Il comportamento di ogni agente è
   condizionato da *(orizzonte temporale × profilo di coppia × regime di mercato)*.
   Lo stesso indicatore ha soglie diverse su BTC/USDT scalping e su XAU/USD investor.
2. **Separazione proposta → validazione → esecuzione.** Nessun agente di
   strategia può eseguire ordini direttamente. I segnali sono *proposte* che
   attraversano validazione e risk gate.
3. **Degradazione controllata.** Ogni dipendenza esterna (feed, broker, LLM) ha
   un circuit breaker e una modalità degradata. Il sistema preferisce *non
   operare* piuttosto che operare alla cieca.
4. **Auto-adattamento misurabile.** Ogni agente espone metriche di performance
   per regime; i parametri si adattano online; gli agenti che sotto-performano
   vengono messi in quarantena automaticamente.
5. **Collaborazione esplicita.** Gli agenti comunicano su un message bus e una
   blackboard condivisa; le decisioni finali nascono da consenso pesato.

---

## 2. Macro-architettura

```
                         ┌───────────────────────────────────────┐
                         │            ORCHESTRATORE                │
                         │   Router  +  Validator  +  Supervisor   │
                         └───────────────┬───────────────────────┘
                                         │ instrada (profilo×regime×orizzonte)
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
 ┌──────────────┐                ┌──────────────┐                ┌──────────────┐
 │ DESK SCALPING│                │ DESK DAY-TRAD│                │ DESK INVESTOR│
 │ (secondi-min)│                │ (min-ore)    │                │ (giorni-mesi)│
 └──────┬───────┘                └──────┬───────┘                └──────┬───────┘
        │ proposte di segnale           │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                         ┌───────────────────────────────────────┐
                         │   VALIDATOR  →  RISK MANAGER  →  EXEC   │
                         └───────────────┬───────────────────────┘
                                         ▼
                         ┌───────────────────────────────────────┐
                         │  PORTFOLIO / PERFORMANCE  (feedback)    │
                         └───────────────┬───────────────────────┘
                                         │ metriche per-regime
                                         ▼  (loop di auto-adattamento)

 SERVIZI CONDIVISI (trasversali a tutti i desk):
 MarketData · PairClassifier · RegimeDetector · NewsSentiment · RiskManager
 Message Bus (pub/sub) · Blackboard (memoria condivisa) · FaultSupervisor
```

Tre livelli logici:

- **Servizi condivisi** — producono il *contesto* (dati, profilo coppia, regime,
  sentiment) consumato da tutti i desk.
- **Desk di strategia** — Scalping / Day Trading / Investor: producono *proposte*.
- **Pipeline decisionale** — Validator → Risk → Execution → Portfolio, con il
  Portfolio che chiude il loop di feedback verso l'auto-adattamento.

---

## 3. Classificazione per orizzonte temporale

| Dimensione | **Scalping** | **Day Trading** | **Investor** |
|---|---|---|---|
| Holding | secondi – minuti | minuti – ore (flat a fine sessione) | giorni – mesi |
| Timeframe dati | tick, 1s, 1m | 1m, 5m, 15m, 1h | 4h, 1D, 1W |
| Driver primario | microstruttura, order book, flusso | tecnico intraday + news del giorno | fondamentali, macro, trend strutturale |
| Sensibilità costi | **estrema** (spread/fee dominano) | media | bassa |
| Leva tipica | alta | media | bassa / nulla |
| Frequenza decisioni | altissima | alta | bassa |
| Ruolo LLM | minimo (solo veto macro/news) | medio (contesto news intraday) | **alto** (tesi d'investimento, macro) |
| Ruolo quant/ML | **dominante** (latenza) | dominante | di supporto |
| Metrica chiave | PnL al netto costi, hit-rate | profit factor giornaliero | Sharpe/Sortino, drawdown |

Ogni desk è un *contenitore* di agenti specializzati che condividono il mandato
di orizzonte ma si differenziano per **profilo di coppia** e **regime**.

---

## 4. Classificazione delle coppie (per non generalizzare)

Il `PairClassifierAgent` assegna a ogni strumento un **profilo** con attributi
quantitativi. Il router e i desk usano il profilo per *parametrizzare* la logica:
soglie, sizing, time-in-force, slippage atteso, gestione dei gap.

### 4.1 Attributi del profilo

| Attributo | Descrizione | Effetto sul comportamento |
|---|---|---|
| `asset_class` | crypto / forex / equity / commodity | seleziona orari, calendario, regole gap |
| `liquidity_tier` | T1 (altissima) … T4 (illiquida) | sizing max, slippage atteso, aggressività ordini |
| `typical_spread_bps` | spread medio in basis point | soglia minima di edge per lo scalper |
| `volatility_bucket` | low / mid / high / extreme (ATR%) | larghezza stop/target, leva ammessa |
| `session_profile` | 24/7 / sessioni FX / orari di borsa | finestre operative, rischio overnight/gap |
| `news_sensitivity` | low / mid / high | peso del NewsSentimentAgent, blackout pre-evento |
| `correlation_cluster` | es. "USD majors", "L1 crypto", "metalli" | limiti di esposizione aggregata |
| `tick_size` / `lot_size` | granularità prezzo/quantità | arrotondamenti, fattibilità degli ordini |
| `leverage_cap` | leva massima consentita | vincolo per il Risk Manager |

### 4.2 Tassonomia per mercato (esempi, non esaustiva)

**Crypto (24/7, alta volatilità)**
- *Majors* — BTC/USDT, ETH/USDT: T1, spread minimo, adatti a tutti gli orizzonti.
- *Large-cap alt* — SOL, BNB, XRP: T1/T2, più volatili.
- *Mid/low-cap alt* — T3/T4: illiquide, slippage alto → scalping sconsigliato,
  sizing ridotto, edge richiesto molto più alto.
- *Stablecoin pair* — USDT/USDC: mean-reversion/arbitraggio, volatilità ~0.
- *Perp/Futures vs Spot* — gestione funding rate, basis, liquidazioni.

**Forex (sessioni, leva, news macro)**
- *Majors* — EUR/USD, USD/JPY, GBP/USD: T1, spread strettissimo, guidati dalle sessioni.
- *Minors/cross* — EUR/GBP, EUR/JPY: spread medio.
- *Exotics* — USD/TRY, USD/ZAR: spread ampio, rischio gap e politico → no scalping aggressivo.

**Azioni / Indici (orari di borsa, earnings, gap)**
- *Large-cap liquide* — AAPL, MSFT: gestione apertura/chiusura, earnings blackout.
- *Small/mid-cap* — illiquide, gap notturni → sizing ridotto.
- *ETF / Indici* — SPX, NDX: bassa idiosincrasia, driver macro.

**Materie prime (stagionalità, geopolitica)**
- *Metalli* — XAU/USD, XAG/USD: rifugio, sensibili a tassi/USD.
- *Energia* — WTI, NatGas: alta volatilità, inventory report, stagionalità.
- *Agricole* — stagionalità e meteo dominanti.

> Il router **rifiuta** combinazioni incompatibili: es. scalping su profilo T4
> illiquido con spread > edge atteso viene scartato a monte (vedi §6).

---

## 5. Catalogo degli agenti

Per ogni agente: **Ruolo · Input · Output · Logica decisionale**. Il "tipo"
indica il motore: `LLM` (Claude), `QUANT` (modelli numerici/ML), `IBRIDO`.

### 5.1 Servizi condivisi

#### MarketDataAgent — `QUANT`
- **Ruolo.** Ingestione e normalizzazione di prezzi, order book, volumi da feed
  multipli; rilevazione dati stantii.
- **Input.** Stream dei provider (primario + secondari), calendario di mercato.
- **Output.** `MarketSnapshot` normalizzato (OHLCV multi-timeframe, book L2,
  spread, timestamp, flag di qualità).
- **Logica.** Deduplica, allinea i timestamp, calcola spread/mid; se il feed
  primario è stantio (> soglia) fa **failover** sul secondario e marca i dati
  come degradati (il consumo a valle si adatta o sospende).

#### PairClassifierAgent — `IBRIDO`
- **Ruolo.** Assegna a ogni strumento il profilo di coppia (§4).
- **Input.** Storico prezzi/volumi, metadati strumento, statistiche di spread.
- **Output.** `PairProfile` (cache con refresh periodico).
- **Logica.** Statistiche rolling (ATR%, spread medio, volume) → bucket
  quantitativi; classificazione di cluster/correlazione; un passaggio LLM
  opzionale arricchisce `news_sensitivity` e cluster tematici da contesto testuale.

#### RegimeDetectorAgent — `QUANT/ML`
- **Ruolo.** Etichetta il regime corrente per coppia/timeframe.
- **Input.** `MarketSnapshot`, volatilità realizzata, indicatori di trend.
- **Output.** `Regime ∈ {trending_up, trending_down, ranging, high_volatility, news_driven}`
  con probabilità.
- **Logica.** Modello a stati (es. HMM / classificatore su feature: ADX, ampiezza
  di banda, autocorrelazione, vol realizzata). Il regime **commuta** i parametri
  e abilita/disabilita i desk (es. ranging → mean-reversion; news_driven → blackout).

#### NewsSentimentAgent — `LLM`
- **Ruolo.** Trasforma news/social/eventi macro in un segnale strutturato di
  sentiment e rischio-evento.
- **Input.** Feed news/headline, calendario economico, post rilevanti; il
  `PairProfile` per pesare la rilevanza.
- **Output.** `SentimentSignal` (polarità −1..+1, confidenza, orizzonte di
  impatto, eventi imminenti con timestamp, lista di pair impattate).
- **Logica.** Claude con **tool use** (`fetch_headlines`, `economic_calendar`) e
  **adaptive thinking**; output **strutturato** (schema JSON) per essere
  machine-readable. Genera **blackout window** pre-evento ad alto impatto che il
  Risk Manager fa rispettare. Su `news_sensitivity=high` il suo peso aumenta.

### 5.2 Desk Scalping (orizzonte secondi–minuti)

Agenti tipici: `OrderFlowScalper`, `SpreadMeanReversionScalper`,
`MicroBreakoutScalper`. Tutti `QUANT` per latenza.

- **Ruolo.** Catturare micro-movimenti sfruttando microstruttura e flusso.
- **Input.** Book L2, trade tape, spread, `PairProfile` (T1 obbligatorio),
  `Regime`, eventuale veto del NewsSentiment.
- **Output.** `Signal` (lato, prezzo, dimensione piccola, TIF brevissimo, stop/target
  in tick, confidenza).
- **Logica.**
  - *OrderFlowScalper*: sbilanciamento del book / aggressività dei trade →
    segue il flusso quando l'imbalance supera una soglia adattiva.
  - *SpreadMeanReversion*: su pair a bassa volatilità (es. stablecoin) opera il
    ritorno alla media quando il prezzo devia oltre k·σ.
  - *MicroBreakout*: rottura di micro-livelli con conferma di volume.
  - **Gate costi:** ogni segnale richiede `edge_atteso > spread + 2·fee`; se il
    profilo non è T1 o `spread_bps` è alto, il segnale è scartato a monte.

### 5.3 Desk Day Trading (orizzonte minuti–ore)

Agenti tipici: `TrendIntradayAgent`, `RangeReversionAgent`, `BreakoutAgent`,
`MomentumAgent`. `IBRIDO` (segnale quant + contesto LLM).

- **Ruolo.** Operare movimenti intraday allineati a regime e contesto del giorno;
  chiudere (o ridurre) a fine sessione per profili con rischio overnight.
- **Input.** OHLCV 1m–1h, indicatori (EMA, RSI, VWAP, ATR, livelli S/R),
  `Regime`, `SentimentSignal`, `PairProfile`.
- **Output.** `Signal` (lato, entry, stop/target da ATR, sizing medio, TIF
  giornaliero, confidenza, razionale testuale).
- **Logica.** Ogni agente è **specializzato per regime** e attivato dal router
  solo quando il regime corrisponde:
  - `TrendIntraday` attivo in `trending_*`: pullback su EMA/VWAP nella direzione del trend.
  - `RangeReversion` attivo in `ranging`: fade dei bordi del range.
  - `Breakout` attivo in pre/post compressione di volatilità.
  - `Momentum` su rotture confermate da volume e sentiment concorde.
  - In `news_driven`, i segnali sono sospesi o richiedono conferma esplicita del
    NewsSentimentAgent (collaborazione, §8).

### 5.4 Desk Investor (orizzonte giorni–mesi)

Agenti tipici: `FundamentalThesisAgent` (`LLM`), `MacroRegimeAgent` (`IBRIDO`),
`TrendFollowingAgent` (`QUANT`), `MeanReversionValueAgent` (`QUANT`).

- **Ruolo.** Costruire e mantenere posizioni strutturali su tesi fondamentali e
  macro; ribilanciare lentamente; fungere da **veto macro** sui desk veloci.
- **Input.** Prezzi 4h–1W, fondamentali/on-chain, dati macro, `SentimentSignal`
  a orizzonte lungo, `PairProfile`.
- **Output.** `Signal` a bassa frequenza (target di allocazione, lato, sizing
  ampio ma con leva bassa, tesi testuale, livelli di invalidazione).
- **Logica.**
  - `FundamentalThesisAgent`: Claude con tool use (fondamentali, on-chain,
    documenti) produce una tesi **strutturata** con catalizzatori e condizioni di
    invalidazione; adaptive thinking; alta confidenza solo con evidenze concordi.
  - `TrendFollowing`: trend di lungo periodo (es. incroci di medie lunghe,
    breakout di Donchian) con sizing da volatilità.
  - `MacroRegimeAgent`: definisce il *risk-on/risk-off* globale che modula
    l'esposizione di tutti i desk.

### 5.5 Pipeline decisionale

#### ValidatorAgent — `QUANT/regole + LLM opzionale`
- **Ruolo.** Primo cancello: convalida formale e di coerenza dei segnali.
- **Input.** `Signal` grezzi dai desk, `MarketSnapshot`, `PairProfile`.
- **Output.** `ValidatedSignal` oppure rigetto con motivazione.
- **Logica.** Validazione **multi-livello** (vedi §7): schema → sanità →
  coerenza con profilo/regime → de-duplica e fusione dei segnali in conflitto.

#### RiskManagerAgent — `QUANT`
- **Ruolo.** Autorità finale prima dell'esecuzione; sizing e limiti.
- **Input.** `ValidatedSignal`, stato del portafoglio, limiti, matrice di
  correlazione, blackout dal NewsSentiment.
- **Output.** `Order` dimensionato oppure veto.
- **Logica.** Position sizing (es. frazione di rischio per trade, vol targeting),
  limiti di esposizione per cluster di correlazione, drawdown massimo, leva per
  `leverage_cap`, rispetto delle blackout window. Può attivare il **kill switch**.

#### ExecutionAgent — `QUANT`
- **Ruolo.** Tradurre `Order` in esecuzione presso il broker (paper/live).
- **Input.** `Order`, `MarketSnapshot`, condizioni di liquidità.
- **Output.** `Fill`/`ExecutionReport`.
- **Logica.** Scelta del tipo d'ordine in base al profilo (limit su scalping per
  controllare lo slippage; gestione TWAP/iceberg su size grandi/illiquide);
  retry con backoff su errori transitori; idempotenza con `client_order_id`.

#### PortfolioAgent — `QUANT`
- **Ruolo.** Stato del portafoglio, PnL, performance per regime; **chiude il loop
  di feedback** verso l'auto-adattamento.
- **Input.** `Fill`, prezzi correnti.
- **Output.** `PortfolioState`, `PerformanceReport` per (agente × regime × profilo).
- **Logica.** Mark-to-market, attribuzione PnL al segnale d'origine, calcolo di
  hit-rate/profit factor/Sharpe per agente e regime → questi feed alimentano
  l'adattamento (§9) e il peso di voto in fase di consenso (§8).

#### FaultSupervisor — `QUANT`
- **Ruolo.** Salute del sistema, restart, modalità degradata, kill switch globale.
- **Input.** Heartbeat e stato dei circuit breaker di tutti gli agenti.
- **Output.** Comandi di restart/quarantena/flatten; stato di salute.
- **Logica.** Vedi §7.

---

## 6. Instradamento (routing) delle attività

Il `Router` riceve, per ogni strumento osservato, il contesto prodotto dai
servizi condivisi e decide **quali agenti attivare** e **con quali parametri**.

```
funzione instrada(strumento):
    snapshot  = MarketData.snapshot(strumento)
    se snapshot.degradato e non tollerabile: SOSPENDI(strumento); ritorna
    profilo   = PairClassifier.profilo(strumento)
    regime    = RegimeDetector.regime(strumento, profilo)
    sentiment = NewsSentiment.segnale(strumento, profilo)

    desk_candidati = []
    per ciascun desk in [Scalping, DayTrading, Investor]:
        se desk.ammissibile(profilo, regime, sentiment):      # gate di fattibilità
            agenti = desk.agenti_per_regime(regime)            # specializzazione
            parametri = desk.parametri(profilo, regime)        # niente generalizzazione
            desk_candidati += [(desk, agenti, parametri)]

    pubblica TaskContext(snapshot, profilo, regime, sentiment) sul bus
    per ciascun (desk, agenti, parametri) in desk_candidati:
        per ciascun agente in agenti:
            agente.valuta_async(TaskContext, parametri)        # proposte → Validator
```

**Gate di ammissibilità (esempi).**
- Scalping ammesso solo se `liquidity_tier == T1` **e** `spread_bps` basso **e**
  regime ∈ {trending, high_volatility, ranging-stretto}; vietato in `news_driven`.
- Day Trading sospeso in finestra di blackout pre-evento (da NewsSentiment).
- Investor sempre ammissibile ma a bassa frequenza; ha potere di **veto macro**.

Il routing è **dato-guidato**: la stessa coppia in regimi diversi attiva agenti
diversi con parametri diversi. È così che si evita la generalizzazione.

---

## 7. Validazione e gestione dei guasti

### 7.1 Validazione multi-livello dei segnali

Ogni `Signal` attraversa, in ordine, cancelli che possono rigettarlo:

1. **Schema** — campi obbligatori, tipi, enum validi, prezzo/size > 0,
   `client_order_id` presente. (Rigetto → dead-letter, niente esecuzione.)
2. **Sanità di mercato** — prezzo entro banda plausibile rispetto al mid; size
   compatibile con `tick_size`/`lot_size`; non basato su dati stantii.
3. **Coerenza profilo/regime** — l'agente è ammesso per quel profilo e regime?
   l'edge supera i costi (gate scalping)? rispetta `leverage_cap`?
4. **Fusione/conflitto** — segnali concordi sullo stesso strumento vengono
   aggregati (confidenza pesata); segnali opposti vanno ad **arbitraggio**
   (consenso pesato per performance, §8) o si annullano.
5. **Risk gate** — il RiskManager applica sizing e limiti; ultimo "no" possibile.

Solo ciò che supera tutti i cancelli diventa `Order`.

### 7.2 Gestione dei guasti (fault handling)

| Guasto | Rilevazione | Reazione |
|---|---|---|
| Feed dati stantio/giù | timestamp oltre soglia, gap | failover su feed secondario; marca dati degradati; sospendi scalping |
| Errore broker transitorio | timeout, 5xx | **retry con backoff esponenziale** + jitter; idempotenza via `client_order_id` |
| Errore broker persistente | breaker aperto | sospendi esecuzione sullo strumento; alza alert |
| Crash/timeout di un agente | heartbeat mancante | il **FaultSupervisor** riavvia; modalità degradata senza quel contributo |
| LLM (Claude) non disponibile | eccezione/timeout | retry → **fallback** `claude-opus-4-8 → claude-sonnet-4-6` → euristica cache; gli agenti LLM non bloccano mai i desk quant |
| Refusal LLM | `stop_reason == "refusal"` | tratta come "nessun segnale", logga, prosegui |
| Segnali in conflitto | rilevato dal Validator | arbitraggio per consenso pesato; in caso di parità, nessuna operazione |
| Violazione limiti di rischio | check del RiskManager | veto dell'ordine; se sistemico → **kill switch** (flatten + stop nuovi ordini) |
| Latenza/anomalia globale | metriche del Supervisor | degradazione progressiva → in ultima istanza kill switch globale |

**Circuit breaker** (per dipendenza esterna): stati `CHIUSO → APERTO → SEMIAPERTO`.
Dopo N fallimenti consecutivi si apre (le chiamate falliscono subito / vanno in
fallback); dopo un cooldown passa a semiaperto e prova una chiamata; se ok torna
chiuso. Evita di martellare un servizio in avaria.

**Kill switch.** Condizioni (drawdown giornaliero oltre soglia, perdita feed
critico, anomalia di esecuzione): chiude/azzera le posizioni in modo ordinato e
blocca nuovi ordini fino a sblocco manuale o ripristino delle condizioni.

**Dead-letter queue.** I messaggi/segnali non processabili finiscono in coda per
ispezione, senza bloccare la pipeline.

---

## 8. Collaborazione tra agenti

- **Message bus (pub/sub).** Disaccoppia produttori e consumatori: i servizi
  pubblicano contesto, i desk pubblicano proposte, la pipeline pubblica esiti.
- **Blackboard condivisa.** Memoria comune (regime corrente, sentiment, stato
  del portafoglio, blackout attive) leggibile da tutti senza accoppiamento diretto.
- **Consenso pesato.** Quando più agenti propongono sullo stesso strumento, il
  voto di ciascuno è pesato dalla sua **performance recente nel regime corrente**
  (fornita dal PortfolioAgent). La direzione vince se supera una soglia di
  confidenza aggregata; altrimenti nessuna operazione.
- **Veto gerarchico.** Il desk Investor / `MacroRegimeAgent` può porre un **veto
  risk-off** che riduce o azzera l'esposizione dei desk veloci, anche se i loro
  segnali sono positivi (la macro batte la microstruttura quando è avversa).
- **Negoziazione cross-desk.** In `news_driven`, i desk veloci richiedono
  conferma al `NewsSentimentAgent` prima di operare; se l'evento è imminente,
  la blackout window prevale.

---

## 9. Auto-adattamento

Ogni agente è dotato di un ciclo di adattamento alimentato dal `PortfolioAgent`:

1. **Misura.** Per ogni agente si registrano metriche **per regime e profilo**:
   hit-rate, profit factor, PnL netto costi, drawdown, slippage realizzato.
2. **Adatta i parametri (online).** Le soglie (es. ampiezza dello sbilanciamento
   per lo scalper, k·σ per la mean-reversion, larghezza stop in ATR) si regolano
   con un controllo a feedback / bandit: si rinforza ciò che in *quel* regime ha
   reso, si attenua ciò che ha perso. I parametri restano vincolati entro range
   di sicurezza.
3. **Seleziona il modello per regime.** Un agente può avere più configurazioni;
   il sistema usa quella storicamente migliore nel regime corrente
   (regime-conditioned).
4. **Quarantena automatica (champion/challenger).** Se un agente scende sotto una
   soglia di performance (es. profit factor < 1 su finestra sufficiente) viene
   **disattivato** automaticamente e tenuto in "shadow mode" (genera segnali senza
   eseguire) finché non torna competitivo. Un challenger può sostituirlo.
5. **Adattamento del peso di voto.** Le performance recenti aggiornano il peso di
   ciascun agente nel consenso (§8): l'influenza segue il merito, per regime.

L'adattamento è **conservativo e auditabile**: ogni modifica di parametro è
loggata con la motivazione (quale metrica, su quale finestra, in quale regime),
ed è limitata entro guardrail per evitare derive.

---

## 10. Mappa design → codice

| Sezione | Modulo |
|---|---|
| Tipi condivisi (Signal, PairProfile, Regime, Order…) | `multiagente/core/types.py` |
| Message bus + blackboard | `multiagente/core/messaging.py` |
| BaseAgent + mixin di adattamento (§9) | `multiagente/core/agent.py` |
| Circuit breaker, retry, supervisor, kill switch (§7.2) | `multiagente/core/faults.py` |
| Wrapper Claude (fallback, tool use, adaptive thinking) | `multiagente/llm/claude_client.py` |
| MarketData / PairClassifier / Regime (§5.1) | `multiagente/data/*.py` |
| NewsSentiment LLM (§5.1) | `multiagente/agents/sentiment.py` |
| Desk Scalping / Day / Investor (§5.2–5.4) | `multiagente/agents/*.py` |
| Router (§6) | `multiagente/orchestrator/router.py` |
| Validator multi-livello (§7.1) | `multiagente/orchestrator/validator.py` |
| Risk Manager (§5.5) | `multiagente/risk/risk_manager.py` |
| Execution (§5.5) | `multiagente/execution/execution.py` |
| Portfolio + feedback (§5.5, §9) | `multiagente/portfolio/portfolio.py` |
| Backtest (motore, metriche, report) (§11) | `multiagente/backtest/*.py` |
| Dashboard web (opzionale) | `multiagente/web/app.py` |
| Cablaggio + loop demo | `multiagente/main.py` |

---

## 11. Backtesting

**Principio: stessa pipeline in backtest e in produzione.** Il backtest non
reimplementa la logica: fa *replay* di dati storici attraverso gli stessi
componenti (Router → Validator → Risk → Execution paper → Portfolio). Così ciò
che si misura è esattamente ciò che gira live, e si evita il classico divario
backtest/produzione.

**Flusso.**
1. `HistoricalFeed` espone l'interfaccia `FeedAdapter` e fa avanzare un indice
   temporale condiviso: a ogni step restituisce lo `MarketSnapshot` della barra
   corrente (più la finestra recente per medie/indicatori).
2. L'engine itera le barre e, per ogni strumento, esegue la pipeline completa.
3. Le posizioni si chiudono al tocco di stop/target nel `mark_to_market`; ogni
   trade chiuso è registrato e retroalimenta gli agenti (auto-adattamento §9).
4. A fine serie le posizioni residue sono chiuse forzatamente.

**Metriche** (`backtest/metrics.py`): rendimento totale, volatilità e **Sharpe**
annualizzati, **max drawdown**, **profit factor**, **hit-rate**, numero di trade
— complessivi e **scomposti per agente e per regime**, per capire *dove* e *in
quale contesto* ogni agente genera (o brucia) valore.

**Dati.** Lo scaffold genera serie sintetiche a segmenti di regime
(trend/range/shock) deterministiche per seed (utile offline) **oppure** scarica
**dati reali da Yahoo Finance** senza API key (`data/providers.py`,
`--source yahoo`), coprendo tutti e 4 i mercati. Fallback automatico al sintetico
se la rete è bloccata. Alternative: CSV (`load_csv_series`) o un provider broker,
mantenendo invariato il resto della pipeline.

**Walk-forward (validazione OOS).** `backtest/walkforward.py` divide la storia in
fold a finestra espansiva: su ciascuno adatta i parametri *in-sample*, li congela
(`StrategyAgent.freeze`), poi misura l'*out-of-sample*; le curve OOS dei fold sono
concatenate componendo i rendimenti. Mette alla prova l'auto-adattamento (§9)
contro l'overfitting.

**Realismo e limiti.** Il `PaperBroker` modella spread, slippage e fee; il Risk
Manager rilascia l'esposizione alla chiusura. Restano semplificazioni tipiche da
irrobustire prima di conclusioni operative: *look-ahead bias* (usare solo dati
fino alla barra corrente — qui rispettato dalla finestra), *survivorship bias*
nel paniere, modello di slippage più fedele per ordini grandi/illiquidi,
gestione realistica di gap e funding, e **walk-forward** con
ottimizzazione out-of-sample per validare l'auto-adattamento (§9) senza
overfitting.

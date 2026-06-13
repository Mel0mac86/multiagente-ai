"""Cablaggio del sistema multi-agente + loop demo (ARCHITETTURA.md §10).

Esegue in modalità *paper*: nessun ordine reale. Senza ANTHROPIC_API_KEY gli
agenti LLM usano il fallback euristico, così il loop gira anche offline.

    python -m multiagente.main
"""

from __future__ import annotations

import logging

from .config import SETTINGS
from .core.faults import HealthMonitor, KillSwitch
from .core.messaging import Blackboard, MessageBus
from .data.market_data import MarketDataAgent, StubFeed
from .data.pair_classifier import PairClassifierAgent
from .data.regime import RegimeDetectorAgent
from .agents.sentiment import NewsSentimentAgent
from .agents.scalping import build_scalping_desk
from .agents.day_trading import build_day_trading_desk
from .agents.investor import build_investor_desk
from .core.types import Horizon
from .llm.claude_client import ClaudeClient
from .orchestrator.router import Router
from .orchestrator.validator import ValidatorAgent
from .risk.risk_manager import RiskManagerAgent
from .execution.execution import ExecutionAgent, PaperBroker
from .portfolio.portfolio import PortfolioAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("multiagente")


DEFAULT_BASE_PRICES = {
    "BTC/USDT": 65000.0, "ETH/USDT": 3500.0, "USDT/USDC": 1.0,
    "EUR/USD": 1.08, "USD/TRY": 33.0, "AAPL": 220.0, "SPX": 5600.0,
    "XAU/USD": 2400.0, "WTI": 78.0,
}


def build_system(feeds: list | None = None) -> dict:
    """Costruisce e collega tutti i componenti, restituendoli in un dict.

    ``feeds`` permette di iniettare feed custom (es. lo storico per il backtest);
    se omesso usa due StubFeed (primario + secondario) per la demo live.
    """
    s = SETTINGS

    if feeds is None:
        feeds = [StubFeed("primario", DEFAULT_BASE_PRICES), StubFeed("secondario", DEFAULT_BASE_PRICES)]
    market_data = MarketDataAgent(feeds, s.fault)

    classifier = PairClassifierAgent()
    regime_detector = RegimeDetectorAgent()
    llm = ClaudeClient(s.llm, s.fault)
    sentiment = NewsSentimentAgent(llm)

    # --- desk di strategia ------------------------------------------------- #
    desks = {
        Horizon.SCALPING: build_scalping_desk(),
        Horizon.DAY_TRADING: build_day_trading_desk(),
        Horizon.INVESTOR: build_investor_desk(llm),
    }
    agents_by_name = {a.name: a for agents in desks.values() for a in agents}

    bus, blackboard = MessageBus(), Blackboard()
    router = Router(market_data, classifier, regime_detector, sentiment, desks, bus, blackboard)
    validator = ValidatorAgent(agents_by_name)

    kill = KillSwitch()
    risk = RiskManagerAgent(s.risk, s.capital, kill)
    execution = ExecutionAgent(PaperBroker(), s.fault)
    # on_close=risk.release: alla chiusura di una posizione si libera l'esposizione.
    portfolio = PortfolioAgent(s.capital, agents_by_name, on_close=risk.release)
    health = HealthMonitor(s.fault)

    return dict(
        settings=s, market_data=market_data, classifier=classifier, router=router,
        validator=validator, risk=risk, execution=execution, portfolio=portfolio,
        kill=kill, health=health, llm=llm,
    )


def run_demo(iterations: int = 5) -> None:
    sys = build_system()
    router: Router = sys["router"]
    validator: ValidatorAgent = sys["validator"]
    risk: RiskManagerAgent = sys["risk"]
    execution: ExecutionAgent = sys["execution"]
    portfolio: PortfolioAgent = sys["portfolio"]
    classifier: PairClassifierAgent = sys["classifier"]
    market_data: MarketDataAgent = sys["market_data"]
    kill = sys["kill"]

    logger.info("Modalità: %s | LLM disponibile: %s", sys["settings"].trading_mode, sys["llm"].available)
    symbols = classifier.known_symbols()

    for it in range(iterations):
        logger.info("===== Iterazione %d =====", it + 1)
        if kill.engaged:
            logger.critical("Kill switch attivo: stop del loop")
            break

        prices: dict[str, float] = {}
        for symbol in symbols:
            snap = market_data.snapshot(symbol)
            if snap is None:
                continue
            prices[symbol] = snap.mid

            signals = router.route(symbol)
            if not signals:
                continue
            validated = validator.validate(signals, snap)
            for vsig in validated:
                profile = classifier.profile(symbol)
                order = risk.assess(vsig, profile)
                if order is None:
                    continue
                fill = execution.execute(order, snap)
                if fill is None:
                    continue
                risk.register_fill(order.symbol, order.meta["cluster"], order.meta["exposure_add"])
                portfolio.on_fill(
                    fill, order, source_agent=vsig.signal.agent, regime=vsig.signal.regime,
                )
                logger.info("ESEGUITO %s %s x%.4f @ %.4f (fonti=%s)",
                            order.side.value, order.symbol, fill.quantity, fill.price, vsig.sources)

        # mark-to-market e feedback agli agenti
        portfolio.mark_to_market(prices)
        risk.update_equity(portfolio.state.equity)

    logger.info("Equity finale: %.2f | PnL realizzato: %.2f | Posizioni aperte: %d",
                portfolio.state.equity, portfolio.state.realized_pnl,
                len(portfolio.state.positions))


if __name__ == "__main__":
    run_demo()

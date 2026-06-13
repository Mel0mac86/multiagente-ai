"""Dashboard web mobile-first (FastAPI) — opzionale.

Espone il backtest via HTTP così puoi lanciarlo e vederne i risultati dal
browser dell'iPhone (Safari). Per "funzionare su iPhone" senza server usa
invece il report HTML autonomo: ``python -m multiagente.backtest``.

Avvio:
    pip install fastapi uvicorn
    uvicorn multiagente.web.app:app --host 0.0.0.0 --port 8000
Poi apri http://<ip-del-pc>:8000 da Safari sull'iPhone (stessa rete Wi-Fi).
"""

from __future__ import annotations

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover - dipendenza opzionale
    raise SystemExit(
        "FastAPI non installato. Esegui: pip install fastapi uvicorn\n"
        "Oppure usa il report autonomo: python -m multiagente.backtest"
    ) from exc

from ..backtest.engine import run_backtest
from ..backtest.report import render_html

app = FastAPI(title="Sistema multi-agente — dashboard")


@app.get("/", response_class=HTMLResponse)
def home(steps: int = 300, seed: int = 0) -> str:
    """Esegue un backtest e restituisce il report HTML responsive."""
    metrics = run_backtest(steps=steps, seed=seed)
    return render_html(metrics, title=f"Backtest ({steps} step, seed {seed})")


@app.get("/api/backtest")
def api_backtest(steps: int = 300, seed: int = 0) -> JSONResponse:
    """Backtest in formato JSON (per integrazioni / app native)."""
    m = run_backtest(steps=steps, seed=seed)
    return JSONResponse({
        "total_return": m.total_return,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
        "volatility": m.volatility,
        "n_trades": m.n_trades,
        "hit_rate": m.hit_rate,
        "profit_factor": None if m.profit_factor == float("inf") else m.profit_factor,
        "final_equity": m.final_equity,
        "equity_curve": m.equity_curve,
        "per_agent": {
            k: {"trades": b.trades, "hit_rate": b.hit_rate, "pnl": b.pnl}
            for k, b in m.per_agent.items()
        },
        "per_regime": {
            k: {"trades": b.trades, "hit_rate": b.hit_rate, "pnl": b.pnl}
            for k, b in m.per_regime.items()
        },
    })


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

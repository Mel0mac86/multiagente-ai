"""Metriche di performance del backtest (puro Python, niente dipendenze).

Calcola rendimento totale, CAGR-like, volatilità, Sharpe, max drawdown e, dai
trade chiusi, hit-rate e profit factor — complessivi e per agente/regime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..portfolio.portfolio import Trade


@dataclass
class AgentBreakdown:
    agent: str
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / abs(self.gross_loss)


@dataclass
class BacktestMetrics:
    initial_equity: float
    final_equity: float
    equity_curve: list[float]
    trades: list[Trade]
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    volatility: float = 0.0
    n_trades: int = 0
    hit_rate: float = 0.0
    profit_factor: float = 0.0
    per_agent: dict[str, AgentBreakdown] = field(default_factory=dict)
    per_regime: dict[str, AgentBreakdown] = field(default_factory=dict)


def _bar_returns(curve: list[float]) -> list[float]:
    out = []
    for a, b in zip(curve, curve[1:]):
        out.append((b - a) / a if a else 0.0)
    return out


def _sharpe(returns: list[float], periods_per_year: int = 252) -> tuple[float, float]:
    if len(returns) < 2:
        return 0.0, 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0, 0.0
    sharpe = (mean / std) * math.sqrt(periods_per_year)
    return sharpe, std * math.sqrt(periods_per_year)


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def compute_metrics(
    initial_equity: float,
    equity_curve: list[float],
    trades: list[Trade],
    periods_per_year: int = 252,
) -> BacktestMetrics:
    final = equity_curve[-1] if equity_curve else initial_equity
    rets = _bar_returns(equity_curve)
    sharpe, vol = _sharpe(rets, periods_per_year)

    m = BacktestMetrics(
        initial_equity=initial_equity,
        final_equity=final,
        equity_curve=equity_curve,
        trades=trades,
        total_return=(final - initial_equity) / initial_equity if initial_equity else 0.0,
        max_drawdown=_max_drawdown(equity_curve),
        sharpe=sharpe,
        volatility=vol,
        n_trades=len(trades),
    )

    wins = sum(1 for t in trades if t.pnl >= 0)
    gp = sum(t.pnl for t in trades if t.pnl >= 0)
    gl = sum(t.pnl for t in trades if t.pnl < 0)
    m.hit_rate = wins / len(trades) if trades else 0.0
    m.profit_factor = (gp / abs(gl)) if gl else (float("inf") if gp else 0.0)

    for t in trades:
        _accumulate(m.per_agent, t.agent, t)
        _accumulate(m.per_regime, t.regime.value, t)
    return m


def _accumulate(d: dict[str, AgentBreakdown], key: str, t: Trade) -> None:
    b = d.setdefault(key, AgentBreakdown(agent=key))
    b.trades += 1
    b.pnl += t.pnl
    if t.pnl >= 0:
        b.wins += 1
        b.gross_profit += t.pnl
    else:
        b.gross_loss += t.pnl

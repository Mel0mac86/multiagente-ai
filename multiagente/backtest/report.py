"""Report HTML autonomo e mobile-first del backtest.

Genera un singolo file HTML *self-contained* (CSS inline, grafico SVG inline,
niente JS né dipendenze esterne): si apre in Safari su iPhone — anche offline,
dall'app File — senza alcun server. È il modo più robusto per "funzionare su
iPhone".
"""

from __future__ import annotations

import html

from .metrics import AgentBreakdown, BacktestMetrics


def _sparkline_svg(curve: list[float], width: int = 360, height: int = 140) -> str:
    if len(curve) < 2:
        return ""
    lo, hi = min(curve), max(curve)
    rng = (hi - lo) or 1.0
    n = len(curve)
    pts = []
    for i, v in enumerate(curve):
        x = i / (n - 1) * (width - 8) + 4
        y = height - 4 - (v - lo) / rng * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    up = curve[-1] >= curve[0]
    color = "#16a34a" if up else "#dc2626"
    area = f"4,{height-4} " + polyline + f" {width-4},{height-4}"
    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="none" role="img" aria-label="curva equity">
  <polygon points="{area}" fill="{color}" opacity="0.12"/>
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>
</svg>"""


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _fmt_pf(x: float) -> str:
    return "∞" if x == float("inf") else f"{x:.2f}"


def _metric_card(label: str, value: str, positive: bool | None = None) -> str:
    cls = "" if positive is None else ("pos" if positive else "neg")
    return f'<div class="card"><div class="lbl">{label}</div><div class="val {cls}">{value}</div></div>'


def _breakdown_rows(items: dict[str, AgentBreakdown]) -> str:
    rows = []
    for b in sorted(items.values(), key=lambda x: x.pnl, reverse=True):
        pnl_cls = "pos" if b.pnl >= 0 else "neg"
        rows.append(
            f"<tr><td>{html.escape(b.agent)}</td><td>{b.trades}</td>"
            f"<td>{_fmt_pct(b.hit_rate)}</td><td>{_fmt_pf(b.profit_factor)}</td>"
            f'<td class="{pnl_cls}">{b.pnl:,.2f}</td></tr>'
        )
    return "\n".join(rows)


def render_html(m: BacktestMetrics, title: str = "Backtest — Sistema multi-agente") -> str:
    ret_pos = m.total_return >= 0
    curve_svg = _sparkline_svg(m.equity_curve)
    cards = "".join([
        _metric_card("Rendimento", _fmt_pct(m.total_return), ret_pos),
        _metric_card("Equity finale", f"{m.final_equity:,.0f}"),
        _metric_card("Sharpe", f"{m.sharpe:.2f}", m.sharpe >= 0),
        _metric_card("Max drawdown", _fmt_pct(m.max_drawdown), positive=False),
        _metric_card("Trade", str(m.n_trades)),
        _metric_card("Hit-rate", _fmt_pct(m.hit_rate)),
        _metric_card("Profit factor", _fmt_pf(m.profit_factor), m.profit_factor >= 1),
        _metric_card("Volatilità (ann.)", _fmt_pct(m.volatility)),
    ])
    agent_rows = _breakdown_rows(m.per_agent)
    regime_rows = _breakdown_rows(m.per_regime)

    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="color-scheme" content="light dark"/>
<title>{html.escape(title)}</title>
<style>
  :root {{ --bg:#0b0e14; --card:#151a23; --fg:#e6e9ef; --muted:#8b94a7; --line:#222a38; }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg:#f5f6f8; --card:#fff; --fg:#1a1d24; --muted:#5b6472; --line:#e3e6ec; }}
  }}
  * {{ box-sizing:border-box; -webkit-text-size-adjust:100%; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro",Segoe UI,Roboto,sans-serif;
         padding:max(16px,env(safe-area-inset-top)) 16px calc(24px+env(safe-area-inset-bottom)); }}
  h1 {{ font-size:20px; margin:4px 0 2px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:16px; }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-bottom:18px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 14px; }}
  .lbl {{ color:var(--muted); font-size:12px; }}
  .val {{ font-size:22px; font-weight:650; margin-top:2px; }}
  .pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
  .chart {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:8px; margin-bottom:18px; }}
  h2 {{ font-size:15px; margin:18px 0 8px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
           border:1px solid var(--line); border-radius:14px; overflow:hidden; font-size:14px; }}
  th,td {{ text-align:right; padding:9px 10px; border-bottom:1px solid var(--line); }}
  th:first-child,td:first-child {{ text-align:left; }}
  th {{ color:var(--muted); font-weight:600; font-size:12px; }}
  tr:last-child td {{ border-bottom:none; }}
  .foot {{ color:var(--muted); font-size:11px; margin-top:20px; }}
</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="sub">Modalità paper · capitale iniziale {m.initial_equity:,.0f}</div>
  <div class="grid">{cards}</div>
  <div class="chart"><div class="lbl" style="padding:4px 6px">Curva equity</div>{curve_svg}</div>

  <h2>Performance per agente</h2>
  <table>
    <tr><th>Agente</th><th>Trade</th><th>Hit-rate</th><th>PF</th><th>PnL</th></tr>
    {agent_rows or '<tr><td colspan="5">nessun trade</td></tr>'}
  </table>

  <h2>Performance per regime</h2>
  <table>
    <tr><th>Regime</th><th>Trade</th><th>Hit-rate</th><th>PF</th><th>PnL</th></tr>
    {regime_rows or '<tr><td colspan="5">nessun trade</td></tr>'}
  </table>

  <div class="foot">Materiale didattico. Risultati di simulazione su dati storici;
  non costituiscono consulenza finanziaria né garanzia di risultati futuri.</div>
</body>
</html>"""


def write_report(m: BacktestMetrics, path: str = "report.html", title: str | None = None) -> str:
    html_str = render_html(m, title) if title else render_html(m)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    return path


def render_walkforward_html(result, title: str = "Walk-forward (out-of-sample)") -> str:
    """Report del walk-forward: metriche OOS aggregate + tabella per fold."""
    base = render_html(result.aggregate, title=title)

    fold_rows = []
    for f in result.folds:
        fm = f.metrics
        ret_cls = "pos" if fm.total_return >= 0 else "neg"
        fold_rows.append(
            f"<tr><td>#{f.index + 1}</td><td>{f.train_bars}</td><td>{f.test_bars}</td>"
            f'<td class="{ret_cls}">{_fmt_pct(fm.total_return)}</td>'
            f"<td>{fm.sharpe:.2f}</td><td>{_fmt_pct(fm.max_drawdown)}</td>"
            f"<td>{fm.n_trades}</td></tr>"
        )
    table = (
        "<h2>Fold (in-sample → out-of-sample)</h2><table>"
        "<tr><th>Fold</th><th>Train (barre)</th><th>Test (barre)</th><th>Rend. OOS</th>"
        "<th>Sharpe</th><th>Max DD</th><th>Trade</th></tr>"
        + ("\n".join(fold_rows) or '<tr><td colspan="7">nessun fold</td></tr>')
        + "</table>"
    )
    note = (
        '<div class="sub" style="margin-top:14px">Le metriche in alto sono '
        "<b>aggregate sui soli dati out-of-sample</b> (parametri congelati dopo l'in-sample "
        "di ogni fold), concatenati componendo i rendimenti.</div>"
    )
    # inserisce la tabella dei fold prima del footer
    return base.replace('<div class="foot">', table + note + '<div class="foot">', 1)


def write_walkforward_report(result, path: str = "report.html") -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_walkforward_html(result))
    return path

"""Dashboard PWA mobile-first (FastAPI) — installabile su iPhone.

Avvio:
    pip install fastapi uvicorn
    uvicorn multiagente.web.app:app --host 0.0.0.0 --port 8000

Poi da Safari sull'iPhone apri http://<ip-del-pc>:8000 e usa "Aggiungi alla
schermata Home" per installare la PWA (manifest + service worker + icone).
Per usarla *senza* server, usa invece il report autonomo:
    python -m multiagente.backtest
"""

from __future__ import annotations

try:
    from fastapi import FastAPI, Response
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover - dipendenza opzionale
    raise SystemExit(
        "FastAPI non installato. Esegui: pip install fastapi uvicorn\n"
        "Oppure usa il report autonomo: python -m multiagente.backtest"
    ) from exc

from ..backtest.engine import run_backtest
from ..backtest.walkforward import run_walk_forward
from .icon import chart_icon

app = FastAPI(title="Sistema multi-agente — dashboard")


# --------------------------------------------------------------------------- #
# API                                                                         #
# --------------------------------------------------------------------------- #
def _metrics_json(m) -> dict:
    return {
        "total_return": m.total_return,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
        "volatility": m.volatility,
        "n_trades": m.n_trades,
        "hit_rate": m.hit_rate,
        "profit_factor": None if m.profit_factor == float("inf") else m.profit_factor,
        "final_equity": m.final_equity,
        "initial_equity": m.initial_equity,
        "equity_curve": m.equity_curve,
        "per_agent": {k: {"trades": b.trades, "hit_rate": b.hit_rate, "pnl": b.pnl}
                      for k, b in m.per_agent.items()},
        "per_regime": {k: {"trades": b.trades, "hit_rate": b.hit_rate, "pnl": b.pnl}
                       for k, b in m.per_regime.items()},
    }


@app.get("/api/backtest")
def api_backtest(steps: int = 300, seed: int = 0, source: str = "synthetic",
                 mode: str = "single", folds: int = 4) -> JSONResponse:
    if mode == "walkforward":
        res = run_walk_forward(steps=steps, seed=seed, source=source, n_folds=folds)
        out = _metrics_json(res.aggregate)
        out["folds"] = [
            {"index": f.index, "train_bars": f.train_bars, "test_bars": f.test_bars,
             "total_return": f.metrics.total_return, "sharpe": f.metrics.sharpe,
             "max_drawdown": f.metrics.max_drawdown, "n_trades": f.metrics.n_trades}
            for f in res.folds
        ]
        return JSONResponse(out)
    return JSONResponse(_metrics_json(run_backtest(steps=steps, seed=seed, source=source)))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# PWA: manifest, service worker, icone                                        #
# --------------------------------------------------------------------------- #
@app.get("/manifest.webmanifest")
def manifest() -> Response:
    data = {
        "name": "Sistema multi-agente — Trading",
        "short_name": "Multiagente",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0e14",
        "theme_color": "#0b0e14",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    }
    import json
    return Response(json.dumps(data), media_type="application/manifest+json")


@app.get("/icon-{size}.png")
def icon(size: int) -> Response:
    size = 512 if size >= 512 else 192
    return Response(chart_icon(size), media_type="image/png")


@app.get("/sw.js")
def service_worker() -> Response:
    js = """
const CACHE = 'multiagente-v1';
const ASSETS = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return; // i backtest vanno sempre in rete
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
"""
    return Response(js, media_type="application/javascript")


# --------------------------------------------------------------------------- #
# UI                                                                          #
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _PAGE


_PAGE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="color-scheme" content="dark light"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
<meta name="apple-mobile-web-app-title" content="Multiagente"/>
<link rel="manifest" href="/manifest.webmanifest"/>
<link rel="apple-touch-icon" href="/icon-192.png"/>
<title>Sistema multi-agente — Trading</title>
<style>
  :root{--bg:#0b0e14;--card:#151a23;--fg:#e6e9ef;--muted:#8b94a7;--line:#222a38;--acc:#16a34a;}
  *{box-sizing:border-box;-webkit-text-size-adjust:100%;}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:16px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;
       padding:max(16px,env(safe-area-inset-top)) 16px calc(28px+env(safe-area-inset-bottom));}
  h1{font-size:20px;margin:2px 0 14px;}
  .controls{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;}
  label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px;}
  select,input{width:100%;padding:10px;border-radius:12px;border:1px solid var(--line);
       background:var(--card);color:var(--fg);font-size:16px;}
  button{grid-column:1/-1;padding:14px;border:none;border-radius:14px;background:var(--acc);
       color:#fff;font-size:17px;font-weight:650;}
  button:active{opacity:.8;}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:16px 0;}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;}
  .lbl{color:var(--muted);font-size:12px;}
  .val{font-size:22px;font-weight:650;margin-top:2px;}
  .pos{color:#16a34a;}.neg{color:#dc2626;}
  .chart{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:8px;}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
       border-radius:14px;overflow:hidden;font-size:14px;margin-top:14px;}
  th,td{text-align:right;padding:9px 10px;border-bottom:1px solid var(--line);}
  th:first-child,td:first-child{text-align:left;}
  th{color:var(--muted);font-weight:600;font-size:12px;}tr:last-child td{border-bottom:none;}
  h2{font-size:15px;margin:18px 0 4px;}.muted{color:var(--muted);font-size:12px;}
  #status{color:var(--muted);font-size:13px;min-height:18px;}
</style>
</head>
<body>
  <h1>Sistema multi-agente · Trading</h1>
  <div class="controls">
    <div><label>Modalità</label>
      <select id="mode"><option value="single">Backtest</option>
        <option value="walkforward">Walk-forward (OOS)</option></select></div>
    <div><label>Sorgente</label>
      <select id="source"><option value="synthetic">Sintetica (offline)</option>
        <option value="yahoo">Yahoo (reale)</option></select></div>
    <div><label>Step / barre</label><input id="steps" type="number" value="300" min="50" step="50"/></div>
    <div><label>Seed</label><input id="seed" type="number" value="0" min="0"/></div>
    <div><label>Fold (walk-forward)</label><input id="folds" type="number" value="4" min="2" max="10"/></div>
    <button id="run">Esegui</button>
  </div>
  <div id="status"></div>
  <div class="chart"><div class="lbl" style="padding:4px 6px">Curva equity</div>
    <svg id="curve" viewBox="0 0 360 140" width="100%" preserveAspectRatio="none"></svg></div>
  <div class="grid" id="cards"></div>
  <div id="tables"></div>
  <div class="muted" style="margin-top:20px">Materiale didattico · simulazione su dati storici, non è consulenza finanziaria.</div>

<script>
const $ = id => document.getElementById(id);
const pct = x => (x*100).toFixed(2)+'%';
function card(lbl,val,cls){return `<div class="card"><div class="lbl">${lbl}</div><div class="val ${cls||''}">${val}</div></div>`;}
function drawCurve(c){
  const svg=$('curve'); svg.innerHTML='';
  if(!c||c.length<2)return;
  const lo=Math.min(...c),hi=Math.max(...c),rng=(hi-lo)||1,n=c.length,W=360,H=140;
  const pts=c.map((v,i)=>`${(i/(n-1)*(W-8)+4).toFixed(1)},${(H-4-(v-lo)/rng*(H-8)).toFixed(1)}`).join(' ');
  const up=c[c.length-1]>=c[0], col=up?'#16a34a':'#dc2626';
  svg.innerHTML=`<polygon points="4,${H-4} ${pts} ${W-4},${H-4}" fill="${col}" opacity="0.12"/>`
    +`<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2"/>`;
}
function table(title,obj){
  let rows=Object.entries(obj).sort((a,b)=>b[1].pnl-a[1].pnl)
    .map(([k,v])=>`<tr><td>${k}</td><td>${v.trades}</td><td>${pct(v.hit_rate)}</td><td class="${v.pnl>=0?'pos':'neg'}">${v.pnl.toFixed(2)}</td></tr>`).join('');
  return `<h2>${title}</h2><table><tr><th>Nome</th><th>Trade</th><th>Hit-rate</th><th>PnL</th></tr>${rows||'<tr><td colspan=4>nessun trade</td></tr>'}</table>`;
}
async function run(){
  const q=new URLSearchParams({mode:$('mode').value,source:$('source').value,
    steps:$('steps').value,seed:$('seed').value,folds:$('folds').value});
  $('status').textContent='Esecuzione in corso…'; $('run').disabled=true;
  try{
    const r=await fetch('/api/backtest?'+q); const m=await r.json();
    drawCurve(m.equity_curve);
    const pf = m.profit_factor==null?'∞':m.profit_factor.toFixed(2);
    $('cards').innerHTML=[
      card('Rendimento',pct(m.total_return),m.total_return>=0?'pos':'neg'),
      card('Equity finale',Math.round(m.final_equity).toLocaleString()),
      card('Sharpe',m.sharpe.toFixed(2),m.sharpe>=0?'pos':'neg'),
      card('Max drawdown',pct(m.max_drawdown),'neg'),
      card('Trade',m.n_trades),card('Hit-rate',pct(m.hit_rate)),
      card('Profit factor',pf,(m.profit_factor==null||m.profit_factor>=1)?'pos':'neg'),
      card('Volatilità',pct(m.volatility)),
    ].join('');
    let t=table('Per agente',m.per_agent)+table('Per regime',m.per_regime);
    if(m.folds){t+='<h2>Fold (OOS)</h2><table><tr><th>Fold</th><th>Train</th><th>Test</th><th>Rend.</th><th>Sharpe</th></tr>'
      +m.folds.map(f=>`<tr><td>#${f.index+1}</td><td>${f.train_bars}</td><td>${f.test_bars}</td><td class="${f.total_return>=0?'pos':'neg'}">${pct(f.total_return)}</td><td>${f.sharpe.toFixed(2)}</td></tr>`).join('')+'</table>';}
    $('tables').innerHTML=t;
    $('status').textContent='Completato.';
  }catch(e){$('status').textContent='Errore: '+e;}
  $('run').disabled=false;
}
$('run').addEventListener('click',run);
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
run();
</script>
</body>
</html>"""

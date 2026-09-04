"""Local trading-activity dashboard for the pump.fun momentum bot.

Run this alongside the bot (in a second terminal, with venv activated):

    python scripts/pumpbot_dashboard.py

Then open http://127.0.0.1:8766 in your browser (it opens automatically).
It reads data/pumpbot_trades.csv directly and refreshes every few seconds
while the bot keeps trading.

Unlike the CSV-only view, the wallet balance panel makes one small,
read-only JSON-RPC call (`getBalance`) to your configured Solana RPC every
~15 seconds to show your real, current SOL balance — that's the one thing
this script sends over the network. It never sends your private key
anywhere; it only ever needs a public wallet address (see
SOLANA_WALLET_ADDRESS in .env.example).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

TRADES_CSV = os.path.join(_ROOT, "data", "pumpbot_trades.csv")
PORT = int(os.environ.get("PUMPBOT_DASHBOARD_PORT", "8766"))

RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
WALLET_ADDRESS = os.environ.get("SOLANA_WALLET_ADDRESS") or None
BALANCE_CACHE_SECONDS = 15

_balance_cache: dict = {"fetched_at": 0.0, "data": None}


def _resolve_wallet_address() -> str | None:
    if WALLET_ADDRESS:
        return WALLET_ADDRESS
    # No public address configured — try deriving one from the private key,
    # if it's set (live-mode setups will have it). Optional: solders may not
    # be installed if the user only ever runs paper mode + this dashboard.
    private_key = os.environ.get("SOLANA_PRIVATE_KEY")
    if not private_key:
        return None
    try:
        from solders.keypair import Keypair

        if private_key.strip().startswith("["):
            key_bytes = bytes(json.loads(private_key))
            return str(Keypair.from_bytes(key_bytes).pubkey())
        return str(Keypair.from_base58_string(private_key.strip()).pubkey())
    except Exception:
        return None


def get_wallet_balance() -> dict:
    """Returns {address, balance_sol, error} — cached briefly to avoid
    hammering the RPC endpoint on every dashboard poll.
    """
    now = time.time()
    if _balance_cache["data"] is not None and now - _balance_cache["fetched_at"] < BALANCE_CACHE_SECONDS:
        return _balance_cache["data"]

    address = _resolve_wallet_address()
    if not address:
        result = {
            "address": None,
            "balance_sol": None,
            "error": "Belum ada wallet dikonfigurasi. Set SOLANA_WALLET_ADDRESS (atau SOLANA_PRIVATE_KEY) di .env.",
        }
        _balance_cache.update(fetched_at=now, data=result)
        return result

    try:
        import requests

        resp = requests.post(
            RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
            timeout=8,
        )
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(str(payload["error"]))
        lamports = payload["result"]["value"]
        result = {"address": address, "balance_sol": lamports / 1_000_000_000, "error": None}
    except Exception as e:
        result = {"address": address, "balance_sol": None, "error": f"Gagal ambil saldo dari RPC: {e}"}

    _balance_cache.update(fetched_at=now, data=result)
    return result


def load_trades() -> list[dict]:
    if not os.path.exists(TRADES_CSV):
        return []
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_summary(rows: list[dict]) -> dict:
    filled_rows = [r for r in rows if r.get("filled", "").strip().lower() == "true"]

    total_volume_sol = sum(float(r["size_sol"]) for r in filled_rows)

    by_strategy: dict[str, dict] = defaultdict(lambda: {"count": 0, "volume_sol": 0.0})
    for r in filled_rows:
        s = by_strategy[r["strategy"]]
        s["count"] += 1
        s["volume_sol"] += float(r["size_sol"])

    # Replay fills chronologically to reconstruct open positions / realized
    # P&L, using the same average-cost accounting as pumpbot/risk.py — this
    # is a read-only, independent view computed straight from the trade log.
    positions: dict[str, dict] = defaultdict(
        lambda: {"token_amount": 0.0, "cost_sol": 0.0, "symbol": ""}
    )
    realized_pnl_sol = 0.0
    volume_timeline = []
    pnl_timeline = []
    running_volume = 0.0

    for r in sorted(filled_rows, key=lambda r: r["timestamp"]):
        mint = r["mint"]
        price = float(r["reference_price_sol"]) if r["reference_price_sol"] else 0.0
        sol = float(r["size_sol"])
        token_amount = sol / price if price > 0 else 0.0
        pos = positions[mint]
        pos["symbol"] = r["symbol"]

        if r["side"] == "BUY":
            pos["token_amount"] += token_amount
            pos["cost_sol"] += sol
        else:  # SELL — the bot always sells the full remaining position
            sell_amount = min(token_amount, pos["token_amount"]) or pos["token_amount"]
            avg_price = pos["cost_sol"] / pos["token_amount"] if pos["token_amount"] else 0.0
            cost_basis = avg_price * sell_amount
            realized_pnl_sol += sol - cost_basis
            pos["token_amount"] -= sell_amount
            pos["cost_sol"] -= cost_basis

        running_volume += sol
        volume_timeline.append({"t": r["timestamp"], "cum_volume": round(running_volume, 6)})
        pnl_timeline.append({"t": r["timestamp"], "cum_pnl": round(realized_pnl_sol, 6)})

    open_positions = [
        {"mint": mint, **p} for mint, p in positions.items() if p["token_amount"] > 1e-9
    ]
    open_exposure_sol = sum(p["cost_sol"] for p in open_positions)

    recent_trades = list(reversed(rows))[:50]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_signals": len(rows),
        "total_filled": len(filled_rows),
        "total_volume_sol": round(total_volume_sol, 6),
        "open_positions_count": len(open_positions),
        "open_exposure_sol": round(open_exposure_sol, 6),
        "realized_pnl_sol": round(realized_pnl_sol, 6),
        "by_strategy": by_strategy,
        "volume_timeline": volume_timeline,
        "pnl_timeline": pnl_timeline,
        "recent_trades": recent_trades,
        "open_positions": sorted(open_positions, key=lambda p: -p["cost_sol"]),
    }


INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pump.fun Bot Dashboard</title>
<style>
  :root {
    --bg: #0b0e14;
    --panel: #131722;
    --panel-border: #232838;
    --text: #e7e9ee;
    --text-dim: #8b93a7;
    --accent: #a78bfa;
    --accent-2: #22c3a6;
    --good: #22c3a6;
    --bad: #f2545b;
    --warn: #e8b339;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 24px 32px 60px;
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 20px;
  }
  h1 { font-size: 20px; margin: 0; font-weight: 600; }
  h1 span { color: var(--text-dim); font-weight: 400; }
  #status {
    font-size: 13px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  #status .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--good);
    box-shadow: 0 0 6px var(--good);
  }
  #status.stale .dot { background: var(--bad); box-shadow: 0 0 6px var(--bad); }

  .wallet-panel {
    background: linear-gradient(135deg, rgba(167,139,250,0.12), rgba(34,195,166,0.08));
    border: 1px solid var(--panel-border);
    border-radius: 14px;
    padding: 20px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 14px;
  }
  .wallet-panel .label { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .wallet-panel .balance { font-size: 34px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .wallet-panel .balance small { font-size: 16px; color: var(--text-dim); font-weight: 500; }
  .wallet-panel .address { font-size: 12px; color: var(--text-dim); font-family: monospace; margin-top: 4px; }
  .wallet-panel .warn-text { font-size: 13px; color: var(--warn); max-width: 460px; }

  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px;
    margin-bottom: 24px;
  }
  .kpi {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 16px 18px;
  }
  .kpi .label { font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }
  .kpi .value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .kpi .value.good { color: var(--good); }
  .kpi .value.bad { color: var(--bad); }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .grid.thirds { grid-template-columns: 1fr 1fr 1fr; }
  @media (max-width: 1000px) { .grid, .grid.thirds { grid-template-columns: 1fr; } }

  .panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .panel h2 {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 14px;
  }
  .chart-wrap { position: relative; height: 220px; }
  .chart-wrap svg { width: 100%; height: 100%; display: block; }

  .bars-wrap { display: flex; flex-direction: column; gap: 14px; justify-content: center; height: 220px; }
  .bar-row { display: grid; grid-template-columns: 90px 1fr 90px; align-items: center; gap: 10px; }
  .bar-label { font-size: 13px; text-transform: capitalize; }
  .bar-count { color: var(--text-dim); font-size: 11px; }
  .bar-track { background: #1c2130; border-radius: 6px; height: 10px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 6px; transition: width 0.3s ease; }
  .bar-value { font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; color: var(--text-dim); }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td {
    text-align: left;
    padding: 8px 6px;
    border-bottom: 1px solid var(--panel-border);
    white-space: nowrap;
  }
  th { color: var(--text-dim); font-weight: 500; font-size: 12px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .table-scroll { max-height: 340px; overflow: auto; }

  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .badge.buy { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.sell { background: rgba(242,84,91,0.15); color: var(--bad); }
  .badge.paper { background: rgba(167,139,250,0.15); color: var(--accent); }
  .badge.live { background: rgba(232,179,57,0.18); color: var(--warn); }
  .badge.filled-yes { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.filled-no { background: rgba(139,147,167,0.15); color: var(--text-dim); }

  .empty { color: var(--text-dim); font-size: 14px; padding: 40px 0; text-align: center; }
  .empty code { background: #1c2130; padding: 2px 6px; border-radius: 4px; }
  footer { margin-top: 28px; color: var(--text-dim); font-size: 12px; text-align: center; }
</style>
</head>
<body>

<header>
  <h1>pump.fun Bot <span>&mdash; Trading Activity</span></h1>
  <div id="status"><span class="dot"></span><span id="status-text">memuat...</span></div>
</header>

<div class="wallet-panel">
  <div>
    <div class="label">Saldo Wallet Utama</div>
    <div class="balance" id="w-balance">&ndash;</div>
    <div class="address" id="w-address"></div>
  </div>
  <div class="warn-text" id="w-warn" hidden></div>
</div>

<div class="kpis">
  <div class="kpi"><div class="label">Total Sinyal</div><div class="value" id="k-signals">&ndash;</div></div>
  <div class="kpi"><div class="label">Trade Ter-fill</div><div class="value" id="k-filled">&ndash;</div></div>
  <div class="kpi"><div class="label">Total Volume</div><div class="value" id="k-volume">&ndash;</div></div>
  <div class="kpi"><div class="label">Eksposur Terbuka</div><div class="value" id="k-exposure">&ndash;</div></div>
  <div class="kpi"><div class="label">Posisi Terbuka</div><div class="value" id="k-positions">&ndash;</div></div>
  <div class="kpi"><div class="label">Realized P&amp;L</div><div class="value" id="k-pnl">&ndash;</div></div>
</div>

<div class="grid">
  <div class="panel">
    <h2>Volume Kumulatif (SOL)</h2>
    <div class="chart-wrap"><svg id="svg-volume" viewBox="0 0 600 220" preserveAspectRatio="none"></svg></div>
  </div>
  <div class="panel">
    <h2>Realized P&amp;L Kumulatif (SOL)</h2>
    <div class="chart-wrap"><svg id="svg-pnl" viewBox="0 0 600 220" preserveAspectRatio="none"></svg></div>
  </div>
</div>

<div class="grid thirds">
  <div class="panel">
    <h2>Per Strategi</h2>
    <div class="bars-wrap" id="strategy-bars"></div>
  </div>
  <div class="panel" style="grid-column: span 2;">
    <h2>Posisi Terbuka</h2>
    <div class="table-scroll">
      <table id="tbl-positions">
        <thead><tr><th>Token</th><th>Mint</th><th class="num">Jumlah Token</th><th class="num">Cost (SOL)</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="empty-positions" hidden>Tidak ada posisi terbuka saat ini.</div>
    </div>
  </div>
</div>

<div class="panel">
  <h2>Trade Terbaru</h2>
  <div class="table-scroll">
    <table id="tbl-trades">
      <thead><tr><th>Waktu</th><th>Mode</th><th>Strategi</th><th>Sisi</th><th>Token</th><th class="num">Harga (SOL)</th><th class="num">SOL</th><th>Status</th><th>Alasan</th></tr></thead>
      <tbody></tbody>
    </table>
    <div class="empty" id="empty-trades" hidden>
      Belum ada aktivitas trading. Jalankan bot dengan <code>python -m pumpbot.main</code> lalu tunggu beberapa siklus.
    </div>
  </div>
</div>

<footer>Trade log auto-refresh tiap 5 detik &middot; saldo wallet auto-refresh tiap 15 detik (satu panggilan RPC read-only) &middot; dibaca dari <code>data/pumpbot_trades.csv</code></footer>

<script>
const fmtSol = (n) => Number(n).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 6}) + ' SOL';
const fmtNum = (n) => Number(n).toLocaleString('en-US', {maximumFractionDigits: 4});
const STRATEGY_COLORS = ['#a78bfa', '#22c3a6', '#e8b339', '#f2545b'];

function renderKpis(d) {
  document.getElementById('k-signals').textContent = d.total_signals;
  document.getElementById('k-filled').textContent = d.total_filled;
  document.getElementById('k-volume').textContent = fmtSol(d.total_volume_sol);
  document.getElementById('k-exposure').textContent = fmtSol(d.open_exposure_sol);
  document.getElementById('k-positions').textContent = d.open_positions_count;

  const pnlEl = document.getElementById('k-pnl');
  pnlEl.textContent = fmtSol(d.realized_pnl_sol);
  pnlEl.className = 'value ' + (d.realized_pnl_sol > 0 ? 'good' : d.realized_pnl_sol < 0 ? 'bad' : '');
}

function renderWallet(w) {
  const balEl = document.getElementById('w-balance');
  const addrEl = document.getElementById('w-address');
  const warnEl = document.getElementById('w-warn');

  if (w.balance_sol !== null && w.balance_sol !== undefined) {
    balEl.innerHTML = Number(w.balance_sol).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 6}) + ' <small>SOL</small>';
  } else {
    balEl.innerHTML = '<small>tidak tersedia</small>';
  }
  addrEl.textContent = w.address || '';
  if (w.error) {
    warnEl.hidden = false;
    warnEl.textContent = w.error;
  } else {
    warnEl.hidden = true;
  }
}

// Hand-drawn SVG area/line charts — no external charting library needed.
function renderAreaChart(svgId, timeline, key, color, allowNegative) {
  const svg = document.getElementById(svgId);
  const w = 600, h = 220, padL = 60, padR = 12, padT = 16, padB = 26;

  if (timeline.length === 0) {
    svg.innerHTML = `<text x="${w/2}" y="${h/2}" fill="#8b93a7" font-size="13" text-anchor="middle">Belum ada data</text>`;
    return;
  }

  const values = timeline.map(p => p[key]);
  let maxV = Math.max(...values, 0.000001);
  let minV = allowNegative ? Math.min(...values, 0) : 0;
  if (maxV === minV) maxV = minV + 0.000001;
  const n = values.length;
  const xStep = n > 1 ? (w - padL - padR) / (n - 1) : 0;
  const xOf = (i) => padL + i * xStep;
  const yOf = (v) => h - padB - ((v - minV) / (maxV - minV)) * (h - padT - padB);

  const points = values.map((v, i) => [xOf(i), yOf(v)]);
  const linePath = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const zeroY = yOf(0);
  const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(1)},${zeroY.toFixed(1)} L${points[0][0].toFixed(1)},${zeroY.toFixed(1)} Z`;

  const firstLabel = new Date(timeline[0].t).toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit'});
  const lastLabel = new Date(timeline[timeline.length - 1].t).toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit'});
  const gradId = svgId + 'Grad';

  svg.innerHTML = `
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    ${minV < 0 ? `<line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${w - padR}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,0.15)" stroke-dasharray="3,3"/>` : ''}
    <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="rgba(255,255,255,0.1)"/>
    <path d="${areaPath}" fill="url(#${gradId})" stroke="none"/>
    <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2"/>
    <text x="4" y="${padT + 6}" fill="#8b93a7" font-size="11">${maxV.toFixed(4)}</text>
    <text x="4" y="${h - padB}" fill="#8b93a7" font-size="11">${minV.toFixed(4)}</text>
    <text x="${padL}" y="${h - 6}" fill="#8b93a7" font-size="11">${firstLabel}</text>
    <text x="${w - padR}" y="${h - 6}" fill="#8b93a7" font-size="11" text-anchor="end">${lastLabel}</text>
  `;
}

function renderStrategyChart(byStrategy) {
  const el = document.getElementById('strategy-bars');
  const entries = Object.entries(byStrategy);
  if (entries.length === 0) {
    el.innerHTML = '<div class="empty">Belum ada data strategi.</div>';
    return;
  }
  const maxVol = Math.max(...entries.map(([, v]) => v.volume_sol), 0.000001);
  el.innerHTML = entries.map(([name, v], i) => `
    <div class="bar-row">
      <div class="bar-label">${name} <span class="bar-count">(${v.count}x)</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${(v.volume_sol / maxVol * 100).toFixed(1)}%; background:${STRATEGY_COLORS[i % STRATEGY_COLORS.length]}"></div></div>
      <div class="bar-value">${fmtSol(v.volume_sol)}</div>
    </div>`).join('');
}

function renderPositions(rows) {
  const tbody = document.querySelector('#tbl-positions tbody');
  document.getElementById('empty-positions').hidden = rows.length > 0;
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td>${p.symbol || '?'}</td>
      <td title="${p.mint}">${p.mint.slice(0, 8)}&hellip;</td>
      <td class="num">${fmtNum(p.token_amount)}</td>
      <td class="num">${fmtSol(p.cost_sol)}</td>
    </tr>`).join('');
}

function renderTrades(rows) {
  const tbody = document.querySelector('#tbl-trades tbody');
  document.getElementById('empty-trades').hidden = rows.length > 0;
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${new Date(r.timestamp).toLocaleTimeString('id-ID')}</td>
      <td><span class="badge ${r.mode}">${r.mode}</span></td>
      <td>${r.strategy}</td>
      <td><span class="badge ${r.side === 'BUY' ? 'buy' : 'sell'}">${r.side}</span></td>
      <td title="${r.mint}">${r.symbol || r.mint.slice(0, 8)}</td>
      <td class="num">${Number(r.reference_price_sol).toFixed(8)}</td>
      <td class="num">${fmtSol(r.size_sol)}</td>
      <td><span class="badge ${r.filled === 'True' ? 'filled-yes' : 'filled-no'}">${r.filled === 'True' ? 'filled' : 'skipped'}</span></td>
      <td>${r.reason}</td>
    </tr>`).join('');
}

async function refreshTrades() {
  const statusEl = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  try {
    const res = await fetch('/api/data', { cache: 'no-store' });
    const d = await res.json();
    renderKpis(d);
    renderAreaChart('svg-volume', d.volume_timeline, 'cum_volume', '#a78bfa', false);
    renderAreaChart('svg-pnl', d.pnl_timeline, 'cum_pnl', '#22c3a6', true);
    renderStrategyChart(d.by_strategy);
    renderPositions(d.open_positions);
    renderTrades(d.recent_trades);
    statusEl.classList.remove('stale');
    statusText.textContent = 'live — update terakhir ' + new Date().toLocaleTimeString('id-ID');
  } catch (e) {
    statusEl.classList.add('stale');
    statusText.textContent = 'gagal memuat data (' + e + ')';
  }
}

async function refreshBalance() {
  try {
    const res = await fetch('/api/balance', { cache: 'no-store' });
    const w = await res.json();
    renderWallet(w);
  } catch (e) {
    renderWallet({ address: null, balance_sol: null, error: String(e) });
  }
}

refreshTrades();
refreshBalance();
setInterval(refreshTrades, 5000);
setInterval(refreshBalance, 15000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - quiet console
        pass

    def _send_json(self, obj) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/api/data"):
            self._send_json(build_summary(load_trades()))
        elif self.path.startswith("/api/balance"):
            self._send_json(get_wallet_balance())
        else:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"pump.fun dashboard jalan di {url} (Ctrl+C untuk berhenti)")
    if not _resolve_wallet_address():
        print(
            "[info] Belum ada SOLANA_WALLET_ADDRESS / SOLANA_PRIVATE_KEY di .env — "
            "panel saldo wallet akan kosong sampai salah satunya diisi."
        )
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard dihentikan.")


if __name__ == "__main__":
    main()

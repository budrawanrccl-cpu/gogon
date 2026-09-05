"""Local control dashboard for the pump.fun copy-trading bot.

Run this alongside the bot (in a second terminal, with venv activated):

    python scripts/pumpfun_dashboard.py

Then open http://127.0.0.1:8766 in your browser (it opens automatically).
It reads data/pumpfun_trades.csv and data/pumpfun_status.json directly —
no extra dependencies, no data sent anywhere — and refreshes every few
seconds while the bot keeps running.

Unlike the read-only Polymarket dashboard, this one can also *control* the
bot: the Pause/Resume button writes data/pumpfun_control.json, which
pumpfun_bot/main.py re-reads once per polling cycle. Pausing stops the bot
from copying any new trades (it keeps scanning/logging what it sees) — it
does not touch positions you already hold.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pumpfun_bot.control import read_control, write_control  # noqa: E402
from pumpfun_bot.status import read_status  # noqa: E402

TRADES_CSV = os.path.join(_ROOT, "data", "pumpfun_trades.csv")
PORT = int(os.environ.get("PF_DASHBOARD_PORT", "8766"))

# A heartbeat older than this many polling intervals is treated as "bot not
# running" rather than just a slow cycle.
STALE_CYCLES = 3


def load_trades() -> list[dict]:
    if not os.path.exists(TRADES_CSV):
        return []
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_summary(rows: list[dict]) -> dict:
    filled_rows = [r for r in rows if r.get("filled", "").strip().lower() == "true"]

    total_volume_sol = sum(float(r["sol_size"]) for r in filled_rows)

    by_side: dict[str, dict] = defaultdict(lambda: {"count": 0, "volume_sol": 0.0})
    for r in filled_rows:
        s = by_side[r["side"]]
        s["count"] += 1
        s["volume_sol"] += float(r["sol_size"])

    # Replay fills chronologically to reconstruct open positions / realized
    # P&L using the same average-cost accounting as pumpfun_bot/risk.py — an
    # independent, read-only view computed straight from the trade log, the
    # same approach as the Polymarket dashboard. Needs token_amount (not just
    # sol_size) to tell a profitable exit from a losing one.
    positions: dict[str, dict] = defaultdict(lambda: {"cost_sol": 0.0, "token_amount": 0.0, "mint": ""})
    realized_pnl_sol = 0.0
    timeline = []
    running_volume = 0.0

    for r in sorted(filled_rows, key=lambda r: r["timestamp"]):
        mint = r["mint"]
        sol = float(r["sol_size"])
        tokens = float(r.get("token_amount") or 0.0)
        pos = positions[mint]
        pos["mint"] = mint

        if r["side"] == "BUY":
            pos["cost_sol"] += sol
            pos["token_amount"] += tokens
        else:  # SELL
            sell_tokens = min(tokens, pos["token_amount"])
            avg_cost = pos["cost_sol"] / pos["token_amount"] if pos["token_amount"] else 0.0
            cost_basis = avg_cost * sell_tokens
            realized_pnl_sol += sol - cost_basis
            pos["token_amount"] -= sell_tokens
            pos["cost_sol"] -= cost_basis

        running_volume += sol
        timeline.append({"t": r["timestamp"], "cum_volume": round(running_volume, 6)})

    open_positions = [p for p in positions.values() if p["cost_sol"] > 1e-9]
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
        "by_side": by_side,
        "timeline": timeline,
        "recent_trades": recent_trades,
        "open_positions": sorted(open_positions, key=lambda p: -p["cost_sol"]),
    }


def build_bot_state() -> dict:
    status = read_status()
    control = read_control()

    running = False
    stale = True
    if status and status.get("updated_at"):
        try:
            updated_at = datetime.fromisoformat(status["updated_at"])
            age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
            interval = status.get("polling_interval_seconds") or 5
            stale = age_seconds > interval * STALE_CYCLES
            running = not stale
        except ValueError:
            pass

    return {
        "running": running,
        "paused": control.get("paused", False),
        "status": status or {},
    }


INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pump.fun Bot Control</title>
<style>
  :root {
    --bg: #0b0e14;
    --panel: #131722;
    --panel-border: #232838;
    --text: #e7e9ee;
    --text-dim: #8b93a7;
    --accent: #b47bff;
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
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 24px;
  }
  h1 { font-size: 20px; margin: 0; font-weight: 600; }
  h1 span { color: var(--text-dim); font-weight: 400; }

  .bot-state { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  #status { font-size: 13px; color: var(--text-dim); display: flex; align-items: center; gap: 6px; }
  #status .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); box-shadow: 0 0 6px var(--good); }
  #status.stale .dot { background: var(--bad); box-shadow: 0 0 6px var(--bad); }
  #status.paused .dot { background: var(--warn); box-shadow: 0 0 6px var(--warn); }

  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600;
  }
  .badge.buy { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.sell { background: rgba(242,84,91,0.15); color: var(--bad); }
  .badge.paper { background: rgba(180,123,255,0.18); color: var(--accent); }
  .badge.live { background: rgba(232,179,57,0.18); color: var(--warn); }
  .badge.filled-yes { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.filled-no { background: rgba(139,147,167,0.15); color: var(--text-dim); }
  .badge.running { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.offline { background: rgba(242,84,91,0.15); color: var(--bad); }
  .badge.paused { background: rgba(232,179,57,0.18); color: var(--warn); }

  #pause-btn {
    border: 1px solid var(--panel-border);
    background: var(--panel);
    color: var(--text);
    padding: 9px 18px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  #pause-btn.is-pause { border-color: rgba(242,84,91,0.4); color: var(--bad); }
  #pause-btn.is-resume { border-color: rgba(34,195,166,0.4); color: var(--good); }
  #pause-btn:disabled { opacity: 0.5; cursor: default; }

  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
  .kpi .value { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .kpi .value.good { color: var(--good); }
  .kpi .value.bad { color: var(--bad); }

  .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 16px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

  .panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .panel h2 {
    font-size: 14px; font-weight: 600; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 0 0 14px;
  }
  .chart-wrap { position: relative; height: 240px; }
  .chart-wrap svg { width: 100%; height: 100%; display: block; }

  .wallet-list { display: flex; flex-direction: column; gap: 8px; }
  .wallet-list code {
    background: #1c2130; padding: 4px 8px; border-radius: 6px; font-size: 12px;
    display: block; overflow-wrap: anywhere;
  }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--panel-border); white-space: nowrap; }
  th { color: var(--text-dim); font-weight: 500; font-size: 12px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .table-scroll { max-height: 360px; overflow: auto; }

  .empty { color: var(--text-dim); font-size: 14px; padding: 40px 0; text-align: center; }
  .empty code { background: #1c2130; padding: 2px 6px; border-radius: 4px; }
  footer { margin-top: 28px; color: var(--text-dim); font-size: 12px; text-align: center; }
</style>
</head>
<body>

<header>
  <h1>pump.fun Bot <span>&mdash; Kontrol &amp; Aktivitas</span></h1>
  <div class="bot-state">
    <span class="badge" id="mode-badge">&ndash;</span>
    <span class="badge" id="run-badge">&ndash;</span>
    <div id="status"><span class="dot"></span><span id="status-text">memuat...</span></div>
    <button id="pause-btn" disabled onclick="togglePause()">&hellip;</button>
  </div>
</header>

<div class="kpis">
  <div class="kpi"><div class="label">Wallet Dipantau</div><div class="value" id="k-wallets">&ndash;</div></div>
  <div class="kpi"><div class="label">Trade Terdeteksi</div><div class="value" id="k-signals">&ndash;</div></div>
  <div class="kpi"><div class="label">Trade Ter-copy</div><div class="value" id="k-filled">&ndash;</div></div>
  <div class="kpi"><div class="label">Total Volume</div><div class="value" id="k-volume">&ndash;</div></div>
  <div class="kpi"><div class="label">Eksposur Terbuka</div><div class="value" id="k-exposure">&ndash;</div></div>
  <div class="kpi"><div class="label">Realized P&amp;L</div><div class="value" id="k-pnl">&ndash;</div></div>
</div>

<div class="grid">
  <div class="panel">
    <h2>Volume Kumulatif</h2>
    <div class="chart-wrap"><svg id="svg-volume" viewBox="0 0 600 220" preserveAspectRatio="none"></svg></div>
  </div>
  <div class="panel">
    <h2>Wallet yang Dipantau</h2>
    <div class="wallet-list" id="wallet-list"></div>
  </div>
</div>

<div class="grid" style="grid-template-columns: 1fr 1fr;">
  <div class="panel">
    <h2>Posisi Terbuka</h2>
    <div class="table-scroll">
      <table id="tbl-positions">
        <thead><tr><th>Mint</th><th class="num">Cost (SOL)</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="empty-positions" hidden>Tidak ada posisi terbuka saat ini.</div>
    </div>
  </div>
  <div class="panel">
    <h2>Trade Terbaru</h2>
    <div class="table-scroll">
      <table id="tbl-trades">
        <thead><tr><th>Waktu</th><th>Mode</th><th>Sisi</th><th>Mint</th><th class="num">SOL</th><th>Status</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="empty-trades" hidden>
        Belum ada aktivitas trading. Jalankan bot dengan <code>python -m pumpfun_bot.main</code> lalu tunggu beberapa siklus.
      </div>
    </div>
  </div>
</div>

<footer>Auto-refresh setiap 5 detik &middot; dibaca langsung dari <code>data/pumpfun_trades.csv</code> &middot; 100% lokal di komputermu</footer>

<script>
const fmtSol = (n) => Number(n).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 6}) + ' SOL';
const fmtNum = (n) => Number(n).toLocaleString('en-US', {maximumFractionDigits: 4});

let currentlyPaused = null; // null = belum tahu, jangan izinkan klik dulu

function renderKpis(d, botState) {
  document.getElementById('k-wallets').textContent = (botState.status.watched_wallets || []).length;
  document.getElementById('k-signals').textContent = d.total_signals;
  document.getElementById('k-filled').textContent = d.total_filled;
  document.getElementById('k-volume').textContent = fmtSol(d.total_volume_sol);
  document.getElementById('k-exposure').textContent = fmtSol(d.open_exposure_sol);

  const pnlEl = document.getElementById('k-pnl');
  pnlEl.textContent = fmtSol(d.realized_pnl_sol);
  pnlEl.className = 'value ' + (d.realized_pnl_sol > 0 ? 'good' : d.realized_pnl_sol < 0 ? 'bad' : '');
}

function renderBotState(botState) {
  const modeBadge = document.getElementById('mode-badge');
  const runBadge = document.getElementById('run-badge');
  const statusEl = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  const btn = document.getElementById('pause-btn');

  const mode = botState.status.mode || '?';
  modeBadge.textContent = mode === 'live' ? 'LIVE' : 'PAPER';
  modeBadge.className = 'badge ' + (mode === 'live' ? 'live' : 'paper');

  if (!botState.running) {
    runBadge.textContent = 'BOT TIDAK JALAN';
    runBadge.className = 'badge offline';
    statusEl.className = 'stale';
    statusText.textContent = 'tidak ada heartbeat terbaru dari python -m pumpfun_bot.main';
  } else if (botState.paused) {
    runBadge.textContent = 'PAUSED';
    runBadge.className = 'badge paused';
    statusEl.className = 'paused';
    statusText.textContent = 'bot jalan tapi dijeda — tidak meng-copy trade baru';
  } else {
    runBadge.textContent = 'AKTIF';
    runBadge.className = 'badge running';
    statusEl.className = '';
    statusText.textContent = 'live — update terakhir ' + new Date().toLocaleTimeString('id-ID');
  }

  currentlyPaused = botState.paused;
  btn.disabled = !botState.running;
  if (botState.paused) {
    btn.textContent = '▶ Resume Bot';
    btn.className = 'is-resume';
  } else {
    btn.textContent = '⏸ Pause Bot';
    btn.className = 'is-pause';
  }
}

function renderWallets(watched) {
  const el = document.getElementById('wallet-list');
  if (!watched || watched.length === 0) {
    el.innerHTML = '<div class="empty">Belum ada wallet dikonfigurasi.</div>';
    return;
  }
  el.innerHTML = watched.map(w => `<code>${w}</code>`).join('');
}

// Hand-drawn SVG area chart — no external charting library needed.
function renderVolumeChart(timeline) {
  const svg = document.getElementById('svg-volume');
  const w = 600, h = 220, padL = 56, padR = 12, padT = 16, padB = 26;

  if (timeline.length === 0) {
    svg.innerHTML = `<text x="${w/2}" y="${h/2}" fill="#8b93a7" font-size="13" text-anchor="middle">Belum ada data</text>`;
    return;
  }

  const values = timeline.map(p => p.cum_volume);
  const maxV = Math.max(...values, 0.0001);
  const n = values.length;
  const xStep = n > 1 ? (w - padL - padR) / (n - 1) : 0;
  const xOf = (i) => padL + i * xStep;
  const yOf = (v) => h - padB - (v / maxV) * (h - padT - padB);

  const points = values.map((v, i) => [xOf(i), yOf(v)]);
  const linePath = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const baseline = h - padB;
  const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(1)},${baseline} L${points[0][0].toFixed(1)},${baseline} Z`;

  const firstLabel = new Date(timeline[0].t).toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit'});
  const lastLabel = new Date(timeline[timeline.length - 1].t).toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit'});

  svg.innerHTML = `
    <defs>
      <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#b47bff" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#b47bff" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <line x1="${padL}" y1="${baseline}" x2="${w - padR}" y2="${baseline}" stroke="rgba(255,255,255,0.1)"/>
    <path d="${areaPath}" fill="url(#volGrad)" stroke="none"/>
    <path d="${linePath}" fill="none" stroke="#b47bff" stroke-width="2"/>
    <text x="4" y="${padT + 6}" fill="#8b93a7" font-size="11">${maxV.toFixed(4)}</text>
    <text x="4" y="${baseline}" fill="#8b93a7" font-size="11">0</text>
    <text x="${padL}" y="${h - 6}" fill="#8b93a7" font-size="11">${firstLabel}</text>
    <text x="${w - padR}" y="${h - 6}" fill="#8b93a7" font-size="11" text-anchor="end">${lastLabel}</text>
  `;
}

function renderPositions(rows) {
  const tbody = document.querySelector('#tbl-positions tbody');
  document.getElementById('empty-positions').hidden = rows.length > 0;
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td>${p.mint.slice(0, 10)}&hellip;</td>
      <td class="num">${fmtNum(p.cost_sol)}</td>
    </tr>`).join('');
}

function renderTrades(rows) {
  const tbody = document.querySelector('#tbl-trades tbody');
  document.getElementById('empty-trades').hidden = rows.length > 0;
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td>${new Date(r.timestamp).toLocaleTimeString('id-ID')}</td>
      <td><span class="badge ${r.mode}">${r.mode}</span></td>
      <td><span class="badge ${r.side === 'BUY' ? 'buy' : 'sell'}">${r.side}</span></td>
      <td>${(r.mint || '').slice(0, 10)}&hellip;</td>
      <td class="num">${Number(r.sol_size).toFixed(4)}</td>
      <td><span class="badge ${r.filled === 'True' ? 'filled-yes' : 'filled-no'}">${r.filled === 'True' ? 'filled' : 'skipped'}</span></td>
    </tr>`).join('');
}

async function togglePause() {
  if (currentlyPaused === null) return;
  const btn = document.getElementById('pause-btn');
  btn.disabled = true;
  try {
    await fetch('/api/control', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({paused: !currentlyPaused}),
    });
  } catch (e) {
    // refresh() below will surface the failure via stale status
  }
  refresh();
}

async function refresh() {
  try {
    const [dataRes, stateRes] = await Promise.all([
      fetch('/api/data', {cache: 'no-store'}),
      fetch('/api/state', {cache: 'no-store'}),
    ]);
    const d = await dataRes.json();
    const botState = await stateRes.json();

    renderKpis(d, botState);
    renderBotState(botState);
    renderWallets(botState.status.watched_wallets);
    renderVolumeChart(d.timeline);
    renderPositions(d.open_positions);
    renderTrades(d.recent_trades);
  } catch (e) {
    document.getElementById('status').className = 'stale';
    document.getElementById('status-text').textContent = 'gagal memuat data (' + e + ')';
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - quiet console
        pass

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/api/data"):
            self._send_json(build_summary(load_trades()))
        elif self.path.startswith("/api/state"):
            self._send_json(build_bot_state())
        else:
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self) -> None:
        if not self.path.startswith("/api/control"):
            self._send_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, status=400)
            return

        updates = {}
        if "paused" in payload:
            updates["paused"] = bool(payload["paused"])
        new_state = write_control(updates)
        self._send_json(new_state)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Dashboard kontrol jalan di {url} (Ctrl+C untuk berhenti)")
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

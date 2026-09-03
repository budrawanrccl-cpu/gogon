"""Local trading-activity dashboard for the Polymarket bot.

Run this alongside the bot (in a second terminal, with venv activated):

    python scripts/dashboard.py

Then open http://127.0.0.1:8765 in your browser (it opens automatically).
It reads data/trades.csv directly — no extra dependencies, no data sent
anywhere — and refreshes every few seconds while the bot keeps trading.
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

TRADES_CSV = os.path.join(_ROOT, "data", "trades.csv")
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))


def load_trades() -> list[dict]:
    if not os.path.exists(TRADES_CSV):
        return []
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_summary(rows: list[dict]) -> dict:
    filled_rows = [r for r in rows if r.get("filled", "").strip().lower() == "true"]

    total_volume_usd = sum(float(r["size_usd"]) for r in filled_rows)

    by_strategy: dict[str, dict] = defaultdict(lambda: {"count": 0, "volume_usd": 0.0})
    for r in filled_rows:
        s = by_strategy[r["strategy"]]
        s["count"] += 1
        s["volume_usd"] += float(r["size_usd"])

    # Replay fills chronologically to reconstruct open positions / realized
    # P&L, using the same average-cost accounting as bot/risk.py — this is a
    # read-only, independent view computed straight from the trade log.
    positions: dict[str, dict] = defaultdict(
        lambda: {"size": 0.0, "cost_usd": 0.0, "market_id": "", "outcome": ""}
    )
    realized_pnl = 0.0
    timeline = []
    running_volume = 0.0

    for r in sorted(filled_rows, key=lambda r: r["timestamp"]):
        token_id = r["token_id"]
        size = float(r["size_shares"])
        usd = float(r["size_usd"])
        pos = positions[token_id]
        pos["market_id"] = r["market_id"]
        pos["outcome"] = r["outcome"]

        if r["side"] == "BUY":
            pos["size"] += size
            pos["cost_usd"] += usd
        else:  # SELL
            sell_size = min(size, pos["size"])
            avg_price = pos["cost_usd"] / pos["size"] if pos["size"] else 0.0
            cost_basis = avg_price * sell_size
            realized_pnl += usd - cost_basis
            pos["size"] -= sell_size
            pos["cost_usd"] -= cost_basis

        running_volume += usd
        timeline.append({"t": r["timestamp"], "cum_volume": round(running_volume, 4)})

    open_positions = [
        {"token_id": tid, **p} for tid, p in positions.items() if p["size"] > 1e-9
    ]
    open_exposure_usd = sum(p["cost_usd"] for p in open_positions)

    recent_trades = list(reversed(rows))[:50]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_signals": len(rows),
        "total_filled": len(filled_rows),
        "total_volume_usd": round(total_volume_usd, 4),
        "open_positions_count": len(open_positions),
        "open_exposure_usd": round(open_exposure_usd, 4),
        "realized_pnl_usd": round(realized_pnl, 4),
        "by_strategy": by_strategy,
        "timeline": timeline,
        "recent_trades": recent_trades,
        "open_positions": sorted(open_positions, key=lambda p: -p["cost_usd"]),
    }


INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket Bot Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0b0e14;
    --panel: #131722;
    --panel-border: #232838;
    --text: #e7e9ee;
    --text-dim: #8b93a7;
    --accent: #5b8def;
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
    margin-bottom: 24px;
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

  .grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
  }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

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
  .chart-wrap { position: relative; height: 240px; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td {
    text-align: left;
    padding: 8px 6px;
    border-bottom: 1px solid var(--panel-border);
    white-space: nowrap;
  }
  th { color: var(--text-dim); font-weight: 500; font-size: 12px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .table-scroll { max-height: 360px; overflow: auto; }

  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
  }
  .badge.buy { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.sell { background: rgba(242,84,91,0.15); color: var(--bad); }
  .badge.paper { background: rgba(91,141,239,0.15); color: var(--accent); }
  .badge.live { background: rgba(232,179,57,0.18); color: var(--warn); }
  .badge.filled-yes { background: rgba(34,195,166,0.15); color: var(--accent-2); }
  .badge.filled-no { background: rgba(139,147,167,0.15); color: var(--text-dim); }

  .empty {
    color: var(--text-dim);
    font-size: 14px;
    padding: 40px 0;
    text-align: center;
  }
  .empty code {
    background: #1c2130;
    padding: 2px 6px;
    border-radius: 4px;
  }
  footer {
    margin-top: 28px;
    color: var(--text-dim);
    font-size: 12px;
    text-align: center;
  }
</style>
</head>
<body>

<header>
  <h1>Polymarket Bot <span>&mdash; Trading Activity</span></h1>
  <div id="status"><span class="dot"></span><span id="status-text">memuat...</span></div>
</header>

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
    <h2>Volume Kumulatif</h2>
    <div class="chart-wrap"><canvas id="chart-volume"></canvas></div>
  </div>
  <div class="panel">
    <h2>Per Strategi</h2>
    <div class="chart-wrap"><canvas id="chart-strategy"></canvas></div>
  </div>
</div>

<div class="grid" style="grid-template-columns: 1fr 1fr;">
  <div class="panel">
    <h2>Posisi Terbuka</h2>
    <div class="table-scroll">
      <table id="tbl-positions">
        <thead><tr><th>Market</th><th>Outcome</th><th class="num">Shares</th><th class="num">Cost ($)</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="empty-positions" hidden>Tidak ada posisi terbuka saat ini.</div>
    </div>
  </div>
  <div class="panel">
    <h2>Trade Terbaru</h2>
    <div class="table-scroll">
      <table id="tbl-trades">
        <thead><tr><th>Waktu</th><th>Mode</th><th>Sisi</th><th>Outcome</th><th class="num">Harga</th><th class="num">$</th><th>Status</th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="empty" id="empty-trades" hidden>
        Belum ada aktivitas trading. Jalankan bot dengan <code>python -m bot.main</code> lalu tunggu beberapa siklus.
      </div>
    </div>
  </div>
</div>

<footer>Auto-refresh setiap 5 detik &middot; dibaca langsung dari <code>data/trades.csv</code> &middot; 100% lokal di komputermu</footer>

<script>
const fmtUsd = (n) => '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtNum = (n) => Number(n).toLocaleString('en-US', {maximumFractionDigits: 4});

let volumeChart, strategyChart;

function ensureCharts() {
  if (volumeChart) return;
  const gridColor = 'rgba(255,255,255,0.06)';
  const textColor = '#8b93a7';

  volumeChart = new Chart(document.getElementById('chart-volume'), {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Volume kumulatif ($)',
      data: [],
      borderColor: '#5b8def',
      backgroundColor: 'rgba(91,141,239,0.15)',
      fill: true,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 2,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor, maxTicksLimit: 6 }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, callback: (v) => '$' + v }, grid: { color: gridColor } },
      },
    },
  });

  strategyChart = new Chart(document.getElementById('chart-strategy'), {
    type: 'doughnut',
    data: { labels: [], datasets: [{ data: [], backgroundColor: ['#5b8def', '#22c3a6', '#e8b339', '#f2545b'] }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: textColor, boxWidth: 10 } } },
    },
  });
}

function renderKpis(d) {
  document.getElementById('k-signals').textContent = d.total_signals;
  document.getElementById('k-filled').textContent = d.total_filled;
  document.getElementById('k-volume').textContent = fmtUsd(d.total_volume_usd);
  document.getElementById('k-exposure').textContent = fmtUsd(d.open_exposure_usd);
  document.getElementById('k-positions').textContent = d.open_positions_count;

  const pnlEl = document.getElementById('k-pnl');
  pnlEl.textContent = fmtUsd(d.realized_pnl_usd);
  pnlEl.className = 'value ' + (d.realized_pnl_usd > 0 ? 'good' : d.realized_pnl_usd < 0 ? 'bad' : '');
}

function renderVolumeChart(timeline) {
  const labels = timeline.map(p => new Date(p.t).toLocaleTimeString('id-ID', {hour: '2-digit', minute: '2-digit', second: '2-digit'}));
  volumeChart.data.labels = labels;
  volumeChart.data.datasets[0].data = timeline.map(p => p.cum_volume);
  volumeChart.update('none');
}

function renderStrategyChart(byStrategy) {
  const labels = Object.keys(byStrategy);
  strategyChart.data.labels = labels.length ? labels : ['(belum ada data)'];
  strategyChart.data.datasets[0].data = labels.length ? labels.map(k => byStrategy[k].volume_usd) : [1];
  strategyChart.update('none');
}

function renderPositions(rows) {
  const tbody = document.querySelector('#tbl-positions tbody');
  document.getElementById('empty-positions').hidden = rows.length > 0;
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td>${p.market_id.slice(0, 10)}&hellip;</td>
      <td>${p.outcome}</td>
      <td class="num">${fmtNum(p.size)}</td>
      <td class="num">${fmtUsd(p.cost_usd)}</td>
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
      <td>${r.outcome}</td>
      <td class="num">${Number(r.price).toFixed(3)}</td>
      <td class="num">${fmtUsd(r.size_usd)}</td>
      <td><span class="badge ${r.filled === 'True' ? 'filled-yes' : 'filled-no'}">${r.filled === 'True' ? 'filled' : 'skipped'}</span></td>
    </tr>`).join('');
}

async function refresh() {
  const statusEl = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  try {
    const res = await fetch('/api/data', { cache: 'no-store' });
    const d = await res.json();
    ensureCharts();
    renderKpis(d);
    renderVolumeChart(d.timeline);
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

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - quiet console
        pass

    def do_GET(self) -> None:
        if self.path.startswith("/api/data"):
            rows = load_trades()
            summary = build_summary(rows)
            body = json.dumps(summary).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
    print(f"Dashboard jalan di {url} (Ctrl+C untuk berhenti)")
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

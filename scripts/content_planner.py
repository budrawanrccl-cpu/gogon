"""Local YouTube content planner — Kanban board for video ideas.

Run:

    python scripts/content_planner.py

Then open http://127.0.0.1:8766 in your browser (it opens automatically).
Ideas are stored in data/content_ideas.json — 100% local, no external
dependencies, nothing sent anywhere. Unrelated to the Polymarket bot; this
is a standalone planning tool that happens to live in the same repo.
"""
from __future__ import annotations

import json
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from content_planner.storage import ContentPlanner  # noqa: E402

DATA_PATH = os.path.join(_ROOT, "data", "content_ideas.json")
PORT = int(os.environ.get("CONTENT_PLANNER_PORT", "8766"))

planner = ContentPlanner(DATA_PATH)

IDEA_ID_RE = re.compile(r"^/api/ideas/(\d+)$")

INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Content Planner</title>
<style>
  :root {
    --bg: #0b0e14;
    --panel: #131722;
    --panel-border: #232838;
    --text: #e7e9ee;
    --text-dim: #8b93a7;
    --accent: #ff4d6d;
    --accent-2: #5b8def;
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
  #status { font-size: 13px; color: var(--text-dim); }

  .panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 20px;
  }
  .panel h2 {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 0 0 14px;
  }

  form.add-form {
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr auto;
    gap: 10px;
  }
  @media (max-width: 800px) { form.add-form { grid-template-columns: 1fr; } }
  form.add-form input, form.add-form textarea {
    background: #1c2130;
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    color: var(--text);
    padding: 9px 10px;
    font-size: 13px;
    font-family: inherit;
  }
  form.add-form button {
    background: var(--accent);
    border: none;
    border-radius: 8px;
    color: white;
    font-weight: 600;
    font-size: 13px;
    padding: 9px 16px;
    cursor: pointer;
  }
  form.add-form button:hover { opacity: 0.9; }

  .board {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
  }
  @media (max-width: 1100px) { .board { grid-template-columns: 1fr 1fr; } }
  @media (max-width: 600px) { .board { grid-template-columns: 1fr; } }

  .column {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    padding: 14px;
    min-height: 120px;
  }
  .column h3 {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin: 0 0 12px;
    display: flex;
    justify-content: space-between;
  }
  .column h3 .count {
    background: #1c2130;
    border-radius: 999px;
    padding: 1px 8px;
    font-size: 11px;
  }

  .card {
    background: #1c2130;
    border: 1px solid var(--panel-border);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 10px;
  }
  .card .title { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .card .topic { font-size: 12px; color: var(--accent-2); margin-bottom: 4px; }
  .card .notes { font-size: 12px; color: var(--text-dim); margin-bottom: 6px; white-space: pre-wrap; }
  .card .date { font-size: 11px; color: var(--warn); margin-bottom: 8px; }
  .card .actions { display: flex; gap: 6px; flex-wrap: wrap; }
  .card button {
    background: transparent;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    color: var(--text-dim);
    font-size: 11px;
    padding: 4px 8px;
    cursor: pointer;
  }
  .card button:hover { color: var(--text); border-color: var(--accent-2); }
  .card button.next { color: var(--good); border-color: var(--good); }
  .card button.outline { color: var(--accent); border-color: var(--accent); }
  .card button.danger:hover { color: var(--bad); border-color: var(--bad); }

  .empty { color: var(--text-dim); font-size: 12px; text-align: center; padding: 12px 0; }

  #outline-box {
    display: none;
    white-space: pre-wrap;
    font-size: 13px;
    background: #1c2130;
    border-radius: 8px;
    padding: 14px;
    margin-top: 10px;
    line-height: 1.5;
  }

  footer { margin-top: 24px; color: var(--text-dim); font-size: 12px; text-align: center; }
</style>
</head>
<body>

<header>
  <h1>YouTube Content Planner <span>&mdash; rencanakan videomu</span></h1>
  <div id="status">memuat...</div>
</header>

<div class="panel">
  <h2>Tambah Ide Video</h2>
  <form class="add-form" id="add-form">
    <input type="text" id="f-title" placeholder="Judul video" required>
    <input type="text" id="f-topic" placeholder="Topik/kategori">
    <input type="date" id="f-date" placeholder="Target upload">
    <button type="submit">+ Tambah</button>
  </form>
</div>

<div class="panel">
  <h2>Outline Generator</h2>
  <form class="add-form" id="outline-form" style="grid-template-columns: 1fr auto;">
    <input type="text" id="o-title" placeholder="Judul video untuk dibuatkan outline">
    <button type="submit">Buat Outline</button>
  </form>
  <div id="outline-box"></div>
</div>

<div class="board" id="board"></div>

<footer>Data tersimpan lokal di <code>data/content_ideas.json</code> &middot; 100% offline, tidak ada data yang dikirim ke mana pun</footer>

<script>
const STAGES = ['idea', 'script', 'record', 'edit', 'published'];
const STAGE_LABELS = {idea: 'Ide', script: 'Riset & Skrip', record: 'Rekam', edit: 'Edit', published: 'Terbit'};

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || ('HTTP ' + res.status));
  }
  return res.status === 204 ? null : res.json();
}

function cardHtml(idea) {
  const isLast = idea.status === 'published';
  return `
    <div class="card" data-id="${idea.id}">
      <div class="title">${escapeHtml(idea.title)}</div>
      ${idea.topic ? `<div class="topic">${escapeHtml(idea.topic)}</div>` : ''}
      ${idea.notes ? `<div class="notes">${escapeHtml(idea.notes)}</div>` : ''}
      ${idea.target_date ? `<div class="date">Target: ${idea.target_date}</div>` : ''}
      <div class="actions">
        ${!isLast ? `<button class="next" onclick="advance(${idea.id})">Lanjut &rarr;</button>` : ''}
        <button class="outline" onclick="fillOutline(${JSON.stringify(idea.title)})">Outline</button>
        <button class="danger" onclick="remove(${idea.id})">Hapus</button>
      </div>
    </div>`;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function refresh() {
  const statusEl = document.getElementById('status');
  try {
    const ideas = await api('/api/ideas');
    const board = document.getElementById('board');
    board.innerHTML = STAGES.map(stage => {
      const items = ideas.filter(i => i.status === stage);
      return `
        <div class="column">
          <h3>${STAGE_LABELS[stage]} <span class="count">${items.length}</span></h3>
          ${items.length ? items.map(cardHtml).join('') : '<div class="empty">Kosong</div>'}
        </div>`;
    }).join('');
    statusEl.textContent = ideas.length + ' ide &middot; update terakhir ' + new Date().toLocaleTimeString('id-ID');
  } catch (e) {
    statusEl.textContent = 'gagal memuat data (' + e + ')';
  }
}

async function advance(id) {
  await api(`/api/ideas/${id}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({advance: true}),
  });
  refresh();
}

async function remove(id) {
  if (!confirm('Hapus ide ini?')) return;
  await api(`/api/ideas/${id}`, {method: 'DELETE'});
  refresh();
}

document.getElementById('add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const title = document.getElementById('f-title').value;
  const topic = document.getElementById('f-topic').value;
  const target_date = document.getElementById('f-date').value;
  try {
    await api('/api/ideas', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, topic, target_date}),
    });
    e.target.reset();
    refresh();
  } catch (err) {
    alert(err.message);
  }
});

function fillOutline(title) {
  document.getElementById('o-title').value = title;
  generateOutline(title);
}

function generateOutline(title) {
  const box = document.getElementById('outline-box');
  const t = (title || 'Videomu').trim();
  box.style.display = 'block';
  box.textContent =
`OUTLINE: ${t}

1. HOOK (0-15 detik)
   - Kalimat pembuka yang bikin penonton penasaran / janji hasil di video ini.

2. INTRO (15-30 detik)
   - Perkenalkan diri singkat + apa yang akan dibahas.
   - Kasih alasan kenapa topik ini penting buat penonton.

3. ISI UTAMA
   - Poin 1: ...
   - Poin 2: ...
   - Poin 3: ...
   (Pecah topik "${t}" jadi 3-5 poin, tiap poin idealnya 1-2 menit.)

4. CALL TO ACTION
   - Ajak subscribe / like / komen dengan pertanyaan spesifik ke penonton.

5. OUTRO
   - Rekap singkat + teaser video berikutnya.`;
}

document.getElementById('outline-form').addEventListener('submit', (e) => {
  e.preventDefault();
  generateOutline(document.getElementById('o-title').value);
});

refresh();
setInterval(refresh, 8000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - quiet console
        pass

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:
        if self.path.startswith("/api/ideas"):
            self._send_json(200, planner.list_ideas())
            return
        body = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/api/ideas":
            try:
                data = self._read_json_body()
                idea = planner.add_idea(
                    title=data.get("title", ""),
                    topic=data.get("topic", ""),
                    notes=data.get("notes", ""),
                    target_date=data.get("target_date", ""),
                )
                self._send_json(201, idea)
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            return
        self._send_json(404, {"error": "not found"})

    def do_PATCH(self) -> None:
        m = IDEA_ID_RE.match(self.path)
        if not m:
            self._send_json(404, {"error": "not found"})
            return
        idea_id = int(m.group(1))
        try:
            data = self._read_json_body()
            if data.get("advance"):
                idea = planner.advance_idea(idea_id)
            else:
                idea = planner.update_idea(idea_id, **data)
            self._send_json(200, idea)
        except KeyError as e:
            self._send_json(404, {"error": str(e)})
        except ValueError as e:
            self._send_json(400, {"error": str(e)})

    def do_DELETE(self) -> None:
        m = IDEA_ID_RE.match(self.path)
        if not m:
            self._send_json(404, {"error": "not found"})
            return
        idea_id = int(m.group(1))
        try:
            planner.delete_idea(idea_id)
            self.send_response(204)
            self.end_headers()
        except KeyError as e:
            self._send_json(404, {"error": str(e)})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Content Planner jalan di {url} (Ctrl+C untuk berhenti)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nContent Planner dihentikan.")


if __name__ == "__main__":
    main()

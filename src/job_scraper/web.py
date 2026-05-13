"""
Web UI for the Job Scraper.

Provides a visual browser-based interface so non-technical users
can search for jobs without touching the command line.

Run:
    uv run job-scraper ui
    uv run python main.py ui
"""

import json
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, send_file

from job_scraper import config
from job_scraper.query_parser import parse_query
from job_scraper.scraper import run_scraper

app = Flask(__name__)

# ── shared state for progress tracking ──
_state = {
    "status": "idle",       # idle | running | done | error
    "progress": [],         # list of log messages
    "result_count": 0,
    "error": "",
}
_state_lock = threading.Lock()


def _reset_state():
    with _state_lock:
        _state["status"] = "idle"
        _state["progress"] = []
        _state["result_count"] = 0
        _state["error"] = ""


def _set_status(status, **kwargs):
    with _state_lock:
        _state["status"] = status
        for k, v in kwargs.items():
            _state[k] = v


def _add_progress(msg):
    with _state_lock:
        _state["progress"].append(msg)


# ── HTML page (embedded for zero-config) ──

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Scraper — Пошук вакансій</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a1a;--surface:rgba(255,255,255,0.04);--surface2:rgba(255,255,255,0.08);
  --border:rgba(255,255,255,0.1);--text:#e4e4ef;--text2:#9d9db8;
  --accent:#6c5ce7;--accent2:#a29bfe;--green:#00b894;--red:#ff6b6b;
  --radius:16px;--font:'Inter',system-ui,sans-serif;
}
html{font-size:16px}
body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;
  display:flex;flex-direction:column;align-items:center;padding:2rem 1rem}
h1{font-size:2rem;font-weight:700;background:linear-gradient(135deg,var(--accent2),var(--green));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.25rem}
.subtitle{color:var(--text2);font-size:.9rem;margin-bottom:2rem}

/* ── card ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:2rem;width:100%;max-width:720px;backdrop-filter:blur(12px);margin-bottom:1.5rem}
.card h2{font-size:1.1rem;font-weight:600;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}

/* ── search ── */
textarea{width:100%;min-height:100px;background:var(--surface2);border:1px solid var(--border);
  border-radius:12px;padding:1rem;color:var(--text);font-family:var(--font);font-size:.95rem;
  resize:vertical;outline:none;transition:border-color .2s}
textarea:focus{border-color:var(--accent)}
textarea::placeholder{color:var(--text2)}

.settings{display:flex;gap:1rem;margin-top:1rem;flex-wrap:wrap;align-items:center}
.settings label{color:var(--text2);font-size:.85rem;display:flex;align-items:center;gap:.4rem}
.settings input[type=number]{width:60px;background:var(--surface2);border:1px solid var(--border);
  border-radius:8px;padding:.4rem .5rem;color:var(--text);font-family:var(--font);outline:none;text-align:center}
.settings select{background:var(--surface2);border:1px solid var(--border);border-radius:8px;
  padding:.4rem .6rem;color:var(--text);font-family:var(--font);outline:none}

.btn{display:inline-flex;align-items:center;gap:.5rem;padding:.75rem 2rem;border-radius:12px;
  border:none;font-family:var(--font);font-size:1rem;font-weight:600;cursor:pointer;
  transition:all .2s;margin-top:1.25rem}
.btn-primary{background:linear-gradient(135deg,var(--accent),#8b7cf7);color:#fff;box-shadow:0 4px 20px rgba(108,92,231,.3)}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 24px rgba(108,92,231,.45)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-download{background:var(--green);color:#fff;padding:.6rem 1.5rem;font-size:.9rem;text-decoration:none;margin-top:1rem}
.btn-download:hover{opacity:.9}

/* ── presets ── */
.presets{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.75rem}
.preset{background:var(--surface2);border:1px solid var(--border);border-radius:10px;
  padding:.4rem .8rem;font-size:.8rem;color:var(--text2);cursor:pointer;transition:all .15s}
.preset:hover{background:var(--accent);color:#fff;border-color:var(--accent)}

/* ── progress ── */
.progress-bar{display:none;margin-top:1.25rem}
.progress-bar.active{display:block}
.progress-track{height:4px;background:var(--surface2);border-radius:4px;overflow:hidden}
.progress-fill{height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--green));
  border-radius:4px;transition:width .3s}
.progress-text{font-size:.82rem;color:var(--text2);margin-top:.5rem}

.spinner{display:inline-block;width:18px;height:18px;border:2px solid rgba(255,255,255,.2);
  border-top-color:var(--accent2);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── log ── */
.log{background:var(--bg);border:1px solid var(--border);border-radius:12px;
  padding:.75rem 1rem;max-height:180px;overflow-y:auto;font-size:.78rem;
  font-family:'SF Mono','Fira Code',monospace;color:var(--text2);margin-top:.75rem;
  display:none;line-height:1.6}
.log.active{display:block}
.log .ok{color:var(--green)}.log .err{color:var(--red)}.log .info{color:var(--accent2)}

/* ── results ── */
.results{display:none}
.results.active{display:block}
.results-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;flex-wrap:wrap;gap:.75rem}
.badge{background:var(--green);color:#fff;padding:.3rem .75rem;border-radius:20px;font-size:.82rem;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:.85rem}
thead{position:sticky;top:0}
th{background:var(--surface2);color:var(--accent2);padding:.6rem .75rem;text-align:left;
  font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.5px}
td{padding:.6rem .75rem;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover td{background:var(--surface2)}
td a{color:var(--accent2);text-decoration:none}
td a:hover{text-decoration:underline}
.table-wrap{max-height:500px;overflow:auto;border-radius:12px;border:1px solid var(--border)}
.desc-cell{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ── examples ── */
.examples{margin-top:1rem}
.examples summary{color:var(--text2);font-size:.85rem;cursor:pointer;user-select:none}
.examples-list{margin-top:.5rem;display:flex;flex-direction:column;gap:.4rem}
.example{font-size:.8rem;color:var(--text2);padding:.4rem .6rem;background:var(--surface2);
  border-radius:8px;cursor:pointer;transition:background .15s;border:1px solid transparent}
.example:hover{background:var(--accent);color:#fff;border-color:var(--accent)}

/* ── responsive ── */
@media(max-width:600px){
  body{padding:1rem .5rem}
  .card{padding:1.25rem}
  h1{font-size:1.5rem}
  .settings{flex-direction:column;align-items:flex-start}
}
</style>
</head>
<body>

<h1>🔍 Job Scraper</h1>
<p class="subtitle">Пошук вакансій на LinkedIn та Indeed — просто опишіть, що шукаєте</p>

<!-- SEARCH CARD -->
<div class="card">
  <h2>📝 Ваш запит</h2>
  <textarea id="query" placeholder="Опишіть, які вакансії шукаєте. Можна українською, російською або англійською.&#10;&#10;Наприклад: знайди мені 100 компаній які шукають 3D hard-surface artist. Шукай remote позиції у ЄС та США."></textarea>

  <div class="presets">
    <span class="preset" onclick="setPreset('3D artist')">🎨 3D Artist</span>
    <span class="preset" onclick="setPreset('data analyst')">📊 Data Analyst</span>
    <span class="preset" onclick="setPreset('product manager')">📋 Product Manager</span>
    <span class="preset" onclick="setPreset('python developer')">🐍 Python Dev</span>
    <span class="preset" onclick="setPreset('UX designer')">✏️ UX Designer</span>
    <span class="preset" onclick="setPreset('marketing manager')">📣 Marketing</span>
  </div>

  <div class="settings">
    <label>⚡ Потоків: <input type="number" id="workers" value="3" min="1" max="10"></label>
  </div>

  <button class="btn btn-primary" id="searchBtn" onclick="startSearch()">
    🚀 Почати пошук
  </button>

  <details class="examples">
    <summary>📖 Приклади запитів (натисніть, щоб розгорнути)</summary>
    <div class="examples-list">
      <div class="example" onclick="useExample(this)">знайди мені 100 компаній які шукають 3D hard-surface artist. Шукай remote позиції у ЄС, США та Канаді. Максимум 2 тижні.</div>
      <div class="example" onclick="useExample(this)">найди 50 вакансий data analyst, удалённо, США и Канада, за последние 7 дней</div>
      <div class="example" onclick="useExample(this)">find 200 companies looking for product manager, remote, EU and USA, last 2 weeks</div>
      <div class="example" onclick="useExample(this)">знайди 30 вакансій python developer, remote, Нідерланди та Німеччина</div>
    </div>
  </details>
</div>

<!-- PROGRESS CARD -->
<div class="card" id="progressCard" style="display:none">
  <h2><span class="spinner"></span> Пошук вакансій...</h2>
  <div class="progress-bar active">
    <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
    <div class="progress-text" id="progressText">Підготовка...</div>
  </div>
  <div class="log active" id="logBox"></div>
</div>

<!-- RESULTS CARD -->
<div class="card results" id="resultsCard">
  <div class="results-header">
    <h2>✅ Результати</h2>
    <span class="badge" id="resultCount">0 вакансій</span>
  </div>
  <a class="btn btn-download" href="/download" id="downloadBtn">📥 Завантажити CSV</a>
  <div class="table-wrap" style="margin-top:1rem">
    <table>
      <thead>
        <tr><th>Компанія</th><th>Позиція</th><th>Локація</th><th>Опис</th><th>Посилання</th></tr>
      </thead>
      <tbody id="resultsBody"></tbody>
    </table>
  </div>
</div>

<!-- PARSED QUERY CARD -->
<div class="card" id="parsedCard" style="display:none">
  <h2>🧠 Розпізнані параметри</h2>
  <div id="parsedInfo" style="font-size:.85rem;color:var(--text2);line-height:1.8"></div>
</div>

<script>
const $ = id => document.getElementById(id);

function setPreset(job) {
  $('query').value = `знайди мені 50 компаній які шукають ${job}. Шукай remote позиції у ЄС, США та Канаді. Максимум 2 тижні.`;
  $('query').focus();
}

function useExample(el) {
  $('query').value = el.textContent;
  $('query').focus();
}

let pollTimer = null;

async function startSearch() {
  const query = $('query').value.trim();
  if (!query) { alert('Будь ласка, введіть запит'); return; }

  const workers = parseInt($('workers').value) || 3;

  // UI state
  $('searchBtn').disabled = true;
  $('searchBtn').innerHTML = '<span class="spinner"></span> Шукаю...';
  $('progressCard').style.display = 'block';
  $('resultsCard').classList.remove('active');
  $('parsedCard').style.display = 'none';
  $('logBox').innerHTML = '';
  $('progressFill').style.width = '0%';
  $('progressText').textContent = 'Надсилаю запит...';

  try {
    // Start the search
    const res = await fetch('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, workers })
    });
    const data = await res.json();

    if (data.parsed) {
      showParsed(data.parsed);
    }

    // Start polling
    $('progressText').textContent = 'Скрейпінг запущено...';
    pollTimer = setInterval(pollStatus, 1000);
  } catch (e) {
    $('progressText').textContent = 'Помилка: ' + e.message;
    resetBtn();
  }
}

function showParsed(p) {
  $('parsedCard').style.display = 'block';
  $('parsedInfo').innerHTML = `
    <div>🎯 <strong>Посада:</strong> ${p.job_title || '(за замовчуванням)'}</div>
    <div>📊 <strong>Кількість:</strong> ${p.count}</div>
    <div>🏠 <strong>Remote:</strong> ${p.remote ? '✅ Так' : '❌ Ні'}</div>
    <div>🌍 <strong>Країни:</strong> ${p.locations.length ? p.locations.join(', ') : 'за замовчуванням'}</div>
    <div>📅 <strong>Давність:</strong> ${p.max_age_hours}г (${Math.round(p.max_age_hours/24)}д)</div>
    <div>💰 <strong>Фільтр зарплати:</strong> ${p.salary_filter ? '✅ Так' : '❌ Ні'}</div>
  `;
}

async function pollStatus() {
  try {
    const res = await fetch('/status');
    const data = await res.json();
    const log = $('logBox');

    // Update log
    if (data.progress && data.progress.length) {
      log.innerHTML = data.progress.map(m => {
        if (m.includes('✓')) return `<div class="ok">${esc(m)}</div>`;
        if (m.includes('✗') || m.includes('fail')) return `<div class="err">${esc(m)}</div>`;
        return `<div class="info">${esc(m)}</div>`;
      }).join('');
      log.scrollTop = log.scrollHeight;
    }

    // Update progress bar (estimate)
    const total = data.progress.filter(m => m.includes('✓') || m.includes('✗')).length;
    const pct = Math.min(95, total * 4);
    $('progressFill').style.width = pct + '%';
    $('progressText').textContent = `Оброблено: ${total} запитів...`;

    if (data.status === 'done') {
      clearInterval(pollTimer);
      $('progressFill').style.width = '100%';
      $('progressText').textContent = `Готово! Знайдено ${data.result_count} вакансій.`;
      if (data.result_count > 0) loadResults();
      resetBtn();
    } else if (data.status === 'error') {
      clearInterval(pollTimer);
      $('progressText').textContent = '❌ Помилка: ' + data.error;
      resetBtn();
    }
  } catch(e) {}
}

async function loadResults() {
  try {
    const res = await fetch('/results');
    const jobs = await res.json();
    const tbody = $('resultsBody');

    $('resultCount').textContent = jobs.length + ' вакансій';
    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td>${esc(j.company)}</td>
        <td><strong>${esc(j.position)}</strong></td>
        <td>${esc(j.location)}</td>
        <td class="desc-cell" title="${esc(j.description)}">${esc(j.description?.substring(0, 120) || '')}</td>
        <td>${j.url ? `<a href="${esc(j.url)}" target="_blank">Відкрити ↗</a>` : '—'}</td>
      </tr>
    `).join('');

    $('resultsCard').classList.add('active');
  } catch(e) {}
}

function resetBtn() {
  $('searchBtn').disabled = false;
  $('searchBtn').innerHTML = '🚀 Почати пошук';
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>"""


# ── Flask routes ──

@app.route("/")
def index():
    return HTML_PAGE


@app.route("/search", methods=["POST"])
def search():
    from flask import request

    data = request.get_json(force=True)
    query_text = data.get("query", "")
    workers = data.get("workers", 3)

    parsed = parse_query(query_text)
    config.MAX_WORKERS = max(1, min(10, workers))

    _reset_state()
    _set_status("running")

    # Return parsed info immediately, scraping runs in background
    thread = threading.Thread(
        target=_run_scraper_background,
        args=(parsed,),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "ok": True,
        "parsed": {
            "job_title": parsed.job_title,
            "count": parsed.count,
            "remote": parsed.remote,
            "locations": parsed.locations,
            "max_age_hours": parsed.max_age_hours,
            "salary_filter": parsed.salary_filter,
        },
    })


@app.route("/status")
def status():
    with _state_lock:
        return jsonify(dict(_state))


@app.route("/results")
def results():
    import pandas as pd

    csv_path = config.JOBS_CSV
    if not csv_path.exists():
        return jsonify([])

    df = pd.read_csv(csv_path)
    cols = ["company", "position", "location", "url", "description"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    records = df[cols].fillna("").head(500).to_dict(orient="records")
    return jsonify(records)


@app.route("/download")
def download():
    csv_path = config.JOBS_CSV
    if not csv_path.exists():
        return "No results yet", 404
    return send_file(str(csv_path), as_attachment=True, download_name="jobs.csv")


def _run_scraper_background(parsed):
    """Run the scraper in a background thread with progress tracking."""
    import builtins
    original_print = builtins.print

    def patched_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        _add_progress(msg)
        original_print(*args, **kwargs)

    builtins.print = patched_print

    try:
        run_scraper(
            locations=parsed.locations or None,
            hours_windows=[parsed.max_age_hours] if parsed.max_age_hours else None,
            keywords=[parsed.job_title] if parsed.job_title else None,
            is_remote=parsed.remote,
            results_wanted=parsed.count,
        )

        # Count results
        import pandas as pd
        if config.JOBS_CSV.exists():
            count = len(pd.read_csv(config.JOBS_CSV))
        else:
            count = 0

        _set_status("done", result_count=count)

    except Exception as e:
        _set_status("error", error=str(e))
    finally:
        builtins.print = original_print


def start_ui(port: int = 8080, no_browser: bool = False):
    """Start the web UI server."""
    url = f"http://localhost:{port}"
    print(f"\n{'=' * 50}")
    print(f"  🌐 Job Scraper UI")
    print(f"  Відкрийте у браузері: {url}")
    print(f"  Для зупинки натисніть Ctrl+C")
    print(f"{'=' * 50}\n")

    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host="0.0.0.0", port=port, debug=False)

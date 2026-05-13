"""
Web UI for the Job Scraper.

Provides a visual browser-based interface so non-technical users
can search for jobs without touching the command line.

Run:
    uv run job-scraper ui
    uv run python main.py ui
"""

import json
import logging
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, send_file

from job_scraper import config
from job_scraper.query_parser import parse_query
from job_scraper.scraper import run_scraper
from job_scraper.processing import process_jobs

# Suppress Flask/Werkzeug access logs (GET /status etc.)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

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
<title>Job Scraper — Minimal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#000000;
  --surface:#0a0a0a;
  --surface-hover:#141414;
  --border:#222;
  --border-focus:#444;
  --text:#ffffff;
  --text-muted:#888888;
  --accent:#ffffff;
  --green:#34d399;
  --red:#f87171;
  --radius:8px;
  --font:'JetBrains Mono', monospace;
  --transition: 0.3s ease;
}
html{font-size:14px; scroll-behavior: smooth;}
body{
  font-family:var(--font);background:var(--bg);color:var(--text);
  min-height:100vh;display:flex;flex-direction:column;align-items:center;
  padding:3rem 1rem;
}
::selection { background: var(--text); color: var(--bg); }

/* Layout & Typography */
h1{font-size:1.5rem;font-weight:700;margin-bottom:0.5rem;letter-spacing:-0.05em;}
.subtitle{color:var(--text-muted);font-size:0.9rem;margin-bottom:3rem;}

.container { width: 100%; max-width: 800px; display: flex; flex-direction: column; gap: 2rem; }

/* Cards */
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:2rem;
  transition: transform var(--transition), border-color var(--transition), box-shadow var(--transition);
  animation: fade-in 0.6s ease-out forwards;
}
.card:hover { border-color: var(--border-focus); }
.card h2{font-size:1rem;font-weight:500;margin-bottom:1.5rem;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-muted);}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Forms & Inputs */
textarea{
  width:100%;min-height:120px;background:var(--bg);border:1px solid var(--border);
  border-radius:var(--radius);padding:1rem;color:var(--text);
  font-family:var(--font);font-size:0.9rem;line-height:1.5;
  resize:vertical;outline:none;transition: border-color var(--transition), box-shadow var(--transition);
}
textarea:focus{border-color:var(--text);box-shadow: 0 0 0 1px var(--text);}
textarea::placeholder{color:var(--text-muted);}

.settings{display:flex;gap:1.5rem;margin-top:1.5rem;align-items:center;font-size:0.9rem;}
.settings label{display:flex;align-items:center;gap:0.5rem;color:var(--text-muted);}
.settings input[type=number]{
  width:60px;background:var(--bg);border:1px solid var(--border);
  border-radius:4px;padding:0.4rem;color:var(--text);font-family:var(--font);
  outline:none;text-align:center;transition: border-color var(--transition);
}
.settings input[type=number]:focus { border-color: var(--text); }

/* Buttons */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:0.5rem;
  padding:0.8rem 1.5rem;border-radius:var(--radius);border:1px solid var(--border);
  font-family:var(--font);font-size:0.9rem;font-weight:500;cursor:pointer;
  background:var(--bg);color:var(--text);transition: all var(--transition);
  margin-top:1.5rem; text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover:not(:disabled){ background:var(--text); color:var(--bg); }
.btn:disabled{opacity:0.5;cursor:not-allowed;}
.btn-primary { background: var(--text); color: var(--bg); border-color: var(--text); }
.btn-primary:hover:not(:disabled) { background: var(--bg); color: var(--text); }
.btn-download{
  background:transparent;color:var(--green);border-color:var(--green);
  text-decoration:none;margin-top:0;
}
.btn-download:hover{background:var(--green);color:var(--bg);}

/* Presets */
.presets{display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:1rem;}
.preset{
  background:transparent;border:1px solid var(--border);border-radius:20px;
  padding:0.3rem 0.8rem;font-size:0.8rem;color:var(--text-muted);
  cursor:pointer;transition:all 0.2s;
}
.preset:hover{border-color:var(--text);color:var(--text);}

/* Progress & Loading */
.progress-container{display:none;}
.progress-container.active{display:block; animation: fade-in 0.4s ease-out;}
.progress-track{
  height:2px;background:var(--border);border-radius:2px;
  overflow:hidden;margin:1rem 0;position:relative;
}
.progress-fill{
  height:100%;width:0%;background:var(--text);
  transition:width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.progress-text{font-size:0.85rem;color:var(--text-muted);display:flex;justify-content:space-between;}

.spinner{
  display:inline-block;width:14px;height:14px;
  border:2px solid var(--border);border-top-color:var(--text);
  border-radius:50%;animation:spin 0.8s linear infinite;
}
.spinner.inverse { border-top-color: var(--bg); border-color: rgba(0,0,0,0.2); }
@keyframes spin{to{transform:rotate(360deg)}}

/* Terminal Log */
.log{
  background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);
  padding:1rem;max-height:200px;overflow-y:auto;font-size:0.8rem;
  color:var(--text-muted);margin-top:1.5rem;line-height:1.6;
  display:none;
}
.log.active{display:block; animation: fade-in 0.4s ease-out;}
.log .ok{color:var(--green);}
.log .err{color:var(--red);}
.log .info{color:var(--text);}
.log-line { border-left: 2px solid transparent; padding-left: 0.5rem; margin-bottom: 0.2rem; }
.log-line:hover { background: var(--surface-hover); border-left-color: var(--border-focus); }

/* Results Table */
.results{display:none;}
.results.active{display:block; animation: fade-in 0.6s ease-out;}
.results-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;}
.badge{background:var(--surface-hover);border:1px solid var(--border);padding:0.2rem 0.6rem;border-radius:4px;font-size:0.8rem;font-weight:500;}

.table-wrap{overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg);}
table{width:100%;border-collapse:collapse;font-size:0.85rem;}
th{
  background:var(--surface);color:var(--text-muted);padding:1rem;
  text-align:left;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;
  border-bottom:1px solid var(--border);
}
td{padding:1rem;border-bottom:1px solid var(--border);vertical-align:top; color:var(--text);}
tr:last-child td { border-bottom: none; }
tr:hover td{background:var(--surface-hover);}
td a{color:var(--text);text-decoration:underline;text-underline-offset:4px;}
td a:hover{color:var(--text-muted);}
.desc-cell{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted);}

/* Parsed Data */
.parsed-card { display: none; }
.parsed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 1rem; }
.parsed-item { background: var(--bg); padding: 1rem; border-radius: var(--radius); border: 1px solid var(--border); }
.parsed-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.5rem; }
.parsed-value { font-size: 0.9rem; font-weight: 500; }

/* Charts */
.analytics-card { display: none; }
.analytics-card.active { display: block; animation: fade-in 0.6s ease-out; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 1.5rem; }
.chart-section h3 { font-size: 0.85rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 1rem; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
.chart-row { display: flex; align-items: center; margin-bottom: 0.6rem; }
.chart-label { width: 120px; font-size: 0.8rem; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chart-bar-bg { flex-grow: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin: 0 1rem; position: relative; }
.chart-bar-fill { height: 100%; background: var(--text); border-radius: 3px; width: 0%; transition: width 1s cubic-bezier(0.4, 0, 0.2, 1); }
.chart-val { font-size: 0.8rem; font-weight: 500; width: 30px; text-align: right; }
@media(max-width:800px){ .chart-grid { grid-template-columns: 1fr; } }

/* Custom Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--border-focus); }

@media(max-width:600px){
  body{padding:1.5rem 0.5rem;}
  .card{padding:1.5rem;}
  .settings{flex-direction:column;align-items:flex-start;}
}
</style>
</head>
<body>

<div class="container">
  <header>
    <h1>> Job Scraper</h1>
    <p class="subtitle">Automated recruitment targeting. Defined by natural language.</p>
  </header>

  <!-- SEARCH CARD -->
  <div class="card">
    <h2>01 // Query Setup</h2>
    <textarea id="query" placeholder="Describe the roles you are looking for.&#10;&#10;e.g. 'find 50 companies hiring 3D artists, remote in EU/US, max 2 weeks old.'"></textarea>

    <div class="presets">
      <span class="preset" onclick="setPreset('3D artist')">3D Artist</span>
      <span class="preset" onclick="setPreset('data analyst')">Data Analyst</span>
      <span class="preset" onclick="setPreset('product manager')">Product Manager</span>
      <span class="preset" onclick="setPreset('python developer')">Python Dev</span>
      <span class="preset" onclick="setPreset('UX designer')">UX Designer</span>
    </div>

    <div class="settings">
      <label>Threads: <input type="number" id="workers" value="3" min="1" max="10"></label>
    </div>

    <button class="btn btn-primary" id="searchBtn" onclick="startSearch()">
      Initialize Search
    </button>
  </div>

  <!-- PARSED QUERY CARD -->
  <div class="card parsed-card" id="parsedCard">
    <h2>02 // Parameter Extraction</h2>
    <div class="parsed-grid" id="parsedInfo"></div>
  </div>

  <!-- PROGRESS CARD -->
  <div class="card progress-container" id="progressCard">
    <h2>03 // Execution Status</h2>
    <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
    <div class="progress-text">
      <span id="progressLabel">Connecting...</span>
      <span id="progressCount">0%</span>
    </div>
    <div class="log" id="logBox"></div>
  </div>

  <!-- RESULTS CARD -->
  <div class="card results" id="resultsCard">
    <div class="results-header">
      <h2>04 // Acquired Targets</h2>
      <div style="display:flex; gap:1rem; align-items:center;">
        <span class="badge" id="resultCount">0 matches</span>
        <a class="btn btn-download" href="/download" id="downloadBtn">Export CSV</a>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Company</th><th>Role</th><th>Location</th><th>Context</th><th>Link</th></tr>
        </thead>
        <tbody id="resultsBody"></tbody>
      </table>
    </div>
  </div>

  <!-- ANALYTICS CARD -->
  <div class="card analytics-card" id="analyticsCard">
    <h2>05 // Data Insights & Salary Analysis</h2>
    <div class="chart-grid" id="analyticsGrid">
      <!-- Injected via JS -->
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);

function setPreset(job) {
  const q = $('query');
  q.value = `find 50 companies hiring ${job}, remote in EU, US, Canada. last 2 weeks.`;
  q.focus();
}

let pollTimer = null;

async function startSearch() {
  const query = $('query').value.trim();
  if (!query) return;

  const workers = parseInt($('workers').value) || 3;

  // UI state transition
  const btn = $('searchBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner inverse"></span> Processing...';
  
  $('progressCard').classList.add('active');
  $('resultsCard').classList.remove('active');
  $('analyticsCard').classList.remove('active');
  $('parsedCard').style.display = 'none';
  $('logBox').innerHTML = '';
  $('logBox').classList.remove('active');
  $('progressFill').style.width = '0%';
  $('progressLabel').textContent = 'Authenticating request...';
  $('progressCount').textContent = '0 / ?';

  // Smooth scroll
  $('progressCard').scrollIntoView({behavior: 'smooth', block: 'nearest'});

  try {
    const res = await fetch('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, workers })
    });
    const data = await res.json();

    if (data.parsed) {
      showParsed(data.parsed);
    }

    $('progressLabel').textContent = 'Initiating web drivers...';
    $('logBox').classList.add('active');
    pollTimer = setInterval(pollStatus, 800);
  } catch (e) {
    $('progressLabel').textContent = 'ERR: ' + e.message;
    resetBtn();
  }
}

function showParsed(p) {
  $('parsedCard').style.display = 'block';
  $('parsedInfo').innerHTML = `
    <div class="parsed-item"><div class="parsed-label">Role</div><div class="parsed-value">${esc(p.job_title || 'Any')}</div></div>
    <div class="parsed-item"><div class="parsed-label">Target Count</div><div class="parsed-value">${p.count}</div></div>
    <div class="parsed-item"><div class="parsed-label">Remote</div><div class="parsed-value">${p.remote ? 'Required' : 'Any'}</div></div>
    <div class="parsed-item"><div class="parsed-label">Region</div><div class="parsed-value">${p.locations.length ? esc(p.locations.join(', ')) : 'Global'}</div></div>
    <div class="parsed-item"><div class="parsed-label">Max Age</div><div class="parsed-value">${Math.round(p.max_age_hours/24)} days</div></div>
  `;
}

async function pollStatus() {
  try {
    const res = await fetch('/status');
    const data = await res.json();
    const log = $('logBox');

    if (data.progress && data.progress.length) {
      // Only append new lines for better performance and animation if wanted, but full redraw is fine for small logs
      log.innerHTML = data.progress.map(m => {
        let cls = 'info';
        if (m.includes('✓')) cls = 'ok';
        else if (m.includes('✗') || m.toLowerCase().includes('fail')) cls = 'err';
        return `<div class="log-line ${cls}">${esc(m)}</div>`;
      }).join('');
      log.scrollTop = log.scrollHeight;
    }

    const total = data.progress.filter(m => m.includes('✓') || m.includes('✗')).length;
    // Attempt to guess progress based on total logs vs target count. Not perfectly accurate but looks active.
    let expected = 20; // arbitrary base
    let countNode = $('parsedInfo').textContent.match(/Target Count\n\s*(\d+)/);
    if (countNode && countNode[1]) expected = parseInt(countNode[1]);
    
    let pct = Math.min(98, Math.max(5, (total / expected) * 100));
    if (data.status === 'running') {
       $('progressFill').style.width = pct + '%';
       $('progressLabel').textContent = 'Extraction in progress...';
       $('progressCount').textContent = `${total} ops`;
    }

    if (data.status === 'done') {
      clearInterval(pollTimer);
      $('progressFill').style.width = '100%';
      $('progressLabel').textContent = 'Extraction complete.';
      $('progressCount').textContent = `Found ${data.result_count}`;
      if (data.result_count > 0) {
        loadResults();
        loadAnalytics();
      }
      resetBtn();
    } else if (data.status === 'error') {
      clearInterval(pollTimer);
      $('progressFill').style.background = 'var(--red)';
      $('progressLabel').textContent = 'Process terminated.';
      resetBtn();
    }
  } catch(e) {}
}

async function loadResults() {
  try {
    const res = await fetch('/results');
    const jobs = await res.json();
    const tbody = $('resultsBody');

    $('resultCount').textContent = jobs.length + ' targets found';
    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td>${esc(j.company)}</td>
        <td style="font-weight:500;">${esc(j.position)}</td>
        <td style="color:var(--text-muted);">${esc(j.location)}</td>
        <td class="desc-cell" title="${esc(j.description)}">${esc(j.description?.substring(0, 80) || '')}...</td>
        <td>${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">Link</a>` : '—'}</td>
      </tr>
    `).join('');

    $('resultsCard').classList.add('active');
    setTimeout(() => {
        $('resultsCard').scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 100);
  } catch(e) {}
}

async function loadAnalytics() {
  try {
    const res = await fetch('/analytics');
    const data = await res.json();
    if (!data.total_jobs) return;

    let html = '';

    const renderBars = (title, items, totalMax) => {
      let block = `<div class="chart-section"><h3>${title}</h3>`;
      if (!items || Object.keys(items).length === 0) {
        block += `<div style="font-size:0.8rem; color:var(--text-muted);">No sufficient data.</div>`;
      } else {
        const maxVal = Math.max(...Object.values(items), totalMax || 1);
        for (const [lbl, val] of Object.entries(items)) {
          const pct = Math.round((val / maxVal) * 100);
          block += `
            <div class="chart-row">
              <div class="chart-label" title="${esc(lbl)}">${esc(lbl)}</div>
              <div class="chart-bar-bg"><div class="chart-bar-fill" style="width:${pct}%"></div></div>
              <div class="chart-val">${val}</div>
            </div>`;
        }
      }
      block += `</div>`;
      return block;
    };

    html += renderBars('Top Locations', data.locations);
    html += renderBars('Top Companies', data.companies);
    
    if (data.salaries) {
      html += renderBars('Est. Salary Distribution', data.salaries);
    } else {
      html += `<div class="chart-section"><h3>Est. Salary Distribution</h3><div style="font-size:0.8rem; color:var(--text-muted);">Not enough salary data found in descriptions.</div></div>`;
    }

    $('analyticsGrid').innerHTML = html;
    $('analyticsCard').classList.add('active');
  } catch(e) {
    console.error(e);
  }
}

function resetBtn() {
  const btn = $('searchBtn');
  btn.disabled = false;
  btn.innerHTML = 'Initialize Search';
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
    parsed.workers = max(1, min(10, workers))

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

    csv_path = config.FINAL_CSV
    if not csv_path.exists():
        return jsonify([])

    df = pd.read_csv(csv_path)
    cols = ["company", "position", "location", "url", "description"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    records = df[cols].fillna("").head(500).to_dict(orient="records")
    return jsonify(records)


@app.route("/analytics")
def analytics():
    import pandas as pd
    import re
    
    csv_path = config.FINAL_CSV
    if not csv_path.exists():
        return jsonify({})
        
    df = pd.read_csv(csv_path)
    if df.empty:
        return jsonify({"total_jobs": 0})
        
    loc_counts = df['location'].value_counts().head(5).to_dict()
    comp_counts = df['company'].value_counts().head(5).to_dict()
    
    salaries = []
    if 'min_amount' in df.columns and 'max_amount' in df.columns:
        for _, row in df.iterrows():
            try:
                mn = float(row.get('min_amount'))
                mx = float(row.get('max_amount'))
                if pd.notna(mn) and pd.notna(mx) and mn > 0:
                    salaries.append((mn + mx) / 2)
            except:
                pass
                
    if len(salaries) < 5:
        for desc in df['description'].dropna():
            matches = re.findall(r'[\$€£]\s*(\d{2,3})[kK]', str(desc))
            for m in matches:
                try:
                    val = float(m) * 1000
                    if 20000 <= val <= 300000: salaries.append(val)
                except:
                    pass
            matches = re.findall(r'[\$€£]\s*(\d{2,3}),(\d{3})', str(desc))
            for m1, m2 in matches:
                try:
                    val = float(m1 + m2)
                    if 20000 <= val <= 300000: salaries.append(val)
                except:
                    pass

    salary_bins = {"< $50k": 0, "$50k-$100k": 0, "$100k-$150k": 0, "> $150k": 0}
    has_salaries = False
    for s in salaries:
        has_salaries = True
        if s < 50000: salary_bins["< $50k"] += 1
        elif s < 100000: salary_bins["$50k-$100k"] += 1
        elif s < 150000: salary_bins["$100k-$150k"] += 1
        else: salary_bins["> $150k"] += 1
        
    return jsonify({
        "locations": loc_counts,
        "companies": comp_counts,
        "salaries": salary_bins if has_salaries else None,
        "total_jobs": len(df)
    })


@app.route("/download")
def download():
    csv_path = config.FINAL_CSV
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
        run_scraper(parsed)
        process_jobs(parsed)

        # Count results
        import pandas as pd
        if config.FINAL_CSV.exists():
            count = len(pd.read_csv(config.FINAL_CSV))
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

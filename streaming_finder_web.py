"""Web interface for the Streaming Finder tool."""

import asyncio
import csv
import io
import os
from functools import partial

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from streaming_finder import (
    STREAMING_VENDORS,
    _fmt_ts,
    LISTS_API_URL,
    DOMAIN_API_URL,
    search_by_technology,
    find_streaming_tech_for_domain,
)

load_dotenv()

app = FastAPI(title="Streaming Finder")


def _get_api_key() -> str:
    key = os.getenv("BUILTWITH_API_KEY", "")
    if not key:
        raise ValueError("BUILTWITH_API_KEY not set in .env")
    return key


async def _search_vendor(api_key: str, vendor_name: str, tech_name: str, limit: int) -> dict:
    """Search a single vendor in a thread (httpx is sync)."""
    loop = asyncio.get_event_loop()
    client = httpx.Client()
    try:
        results = await loop.run_in_executor(
            None, partial(search_by_technology, client, api_key, tech_name, limit)
        )
        for r in results:
            r["vendor"] = vendor_name
        return {"vendor": vendor_name, "tech_name": tech_name, "results": results, "error": None}
    except Exception as e:
        return {"vendor": vendor_name, "tech_name": tech_name, "results": [], "error": str(e)}
    finally:
        client.close()


@app.get("/", response_class=HTMLResponse)
async def index():
    vendors_json = [{"name": k, "tech": v} for k, v in STREAMING_VENDORS.items()]
    import json
    return HTML_TEMPLATE.replace("__VENDORS_JSON__", json.dumps(vendors_json))


@app.post("/api/search")
async def api_search(request: Request):
    body = await request.json()
    vendors = body.get("vendors", list(STREAMING_VENDORS.keys()))
    limit = min(body.get("limit", 50), 500)

    try:
        api_key = _get_api_key()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # Run searches concurrently (max 4 at a time to be nice to the API)
    sem = asyncio.Semaphore(4)

    async def search_with_sem(name, tech):
        async with sem:
            return await _search_vendor(api_key, name, tech, limit)

    tasks = []
    for name in vendors:
        tech = STREAMING_VENDORS.get(name)
        if tech:
            tasks.append(search_with_sem(name, tech))

    results = await asyncio.gather(*tasks)

    all_sites = []
    vendor_summaries = []
    for r in results:
        vendor_summaries.append({
            "vendor": r["vendor"],
            "count": len(r["results"]),
            "error": r["error"],
        })
        all_sites.extend(r["results"])

    return {
        "vendors": vendor_summaries,
        "sites": all_sites,
        "total": len(all_sites),
    }


@app.post("/api/lookup")
async def api_lookup(request: Request):
    body = await request.json()
    domain = body.get("domain", "").strip()
    if not domain:
        return JSONResponse({"error": "domain is required"}, status_code=400)

    try:
        api_key = _get_api_key()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    loop = asyncio.get_event_loop()
    client = httpx.Client()
    try:
        found = await loop.run_in_executor(
            None, partial(find_streaming_tech_for_domain, client, api_key, domain)
        )
        return {"domain": domain, "vendors_found": found}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        client.close()


@app.post("/api/export")
async def api_export(request: Request):
    body = await request.json()
    sites = body.get("sites", [])

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["vendor", "domain", "rank", "first_detected", "last_detected"])
    writer.writeheader()
    for s in sites:
        writer.writerow({
            "vendor": s.get("vendor", ""),
            "domain": s.get("domain", ""),
            "rank": s.get("rank", ""),
            "first_detected": s.get("first_detected", ""),
            "last_detected": s.get("last_detected", ""),
        })
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=streaming_finder_results.csv"},
    )


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Streaming Finder</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface-hover: #1f2231;
    --border: #2a2d3a;
    --text: #e4e4e7;
    --muted: #71717a;
    --green: #22c55e;
    --green-dim: #16352a;
    --red: #ef4444;
    --red-dim: #351616;
    --blue: #3b82f6;
    --blue-dim: #162035;
    --purple: #a855f7;
    --purple-dim: #1e1635;
    --orange: #f97316;
    --cyan: #06b6d4;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", sans-serif;
    background: var(--bg); color: var(--text);
    padding: 24px; max-width: 1400px; margin: 0 auto; line-height: 1.5;
  }

  header {
    display: flex; align-items: center; gap: 16px;
    margin-bottom: 28px; padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }
  header h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }
  header .subtitle { color: var(--muted); font-size: 13px; margin-left: 8px; }

  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 22px; margin-bottom: 24px;
  }
  .card h2 {
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.6px;
    color: var(--muted); margin-bottom: 16px; font-weight: 600;
  }

  .controls { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
  .control-group { display: flex; flex-direction: column; gap: 6px; }
  .control-group label { font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }

  .vendor-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px;
  }
  .vendor-chip {
    display: flex; align-items: center; gap: 8px;
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 12px; cursor: pointer; transition: all 0.15s; font-size: 13px;
    user-select: none;
  }
  .vendor-chip:hover { border-color: var(--blue); background: var(--blue-dim); }
  .vendor-chip.selected { border-color: var(--blue); background: var(--blue-dim); color: var(--blue); }
  .vendor-chip input { display: none; }
  .vendor-chip .check { width: 16px; height: 16px; border: 1.5px solid var(--muted); border-radius: 4px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .vendor-chip.selected .check { border-color: var(--blue); background: var(--blue); }
  .vendor-chip.selected .check::after { content: ""; display: block; width: 5px; height: 9px; border: solid var(--bg); border-width: 0 2px 2px 0; transform: rotate(45deg) translate(-1px, -1px); }

  .btn-row { display: flex; gap: 10px; align-items: center; margin-top: 16px; }
  .btn {
    padding: 8px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;
    cursor: pointer; border: 1px solid var(--border); transition: all 0.15s;
  }
  .btn-primary { background: var(--blue); border-color: var(--blue); color: white; }
  .btn-primary:hover { opacity: 0.9; }
  .btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-secondary { background: transparent; color: var(--muted); }
  .btn-secondary:hover { color: var(--text); border-color: var(--text); }
  .btn-ghost { background: transparent; border: none; color: var(--muted); cursor: pointer; font-size: 13px; }
  .btn-ghost:hover { color: var(--text); }

  input[type="number"], input[type="text"] {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 12px; color: var(--text); font-size: 14px; width: 100%;
    outline: none; transition: border-color 0.15s;
  }
  input:focus { border-color: var(--blue); }
  input[type="number"] { width: 80px; }

  /* Progress */
  .progress-bar { height: 4px; background: var(--border); border-radius: 2px; margin: 16px 0; overflow: hidden; display: none; }
  .progress-bar.active { display: block; }
  .progress-fill { height: 100%; background: var(--blue); border-radius: 2px; transition: width 0.3s; width: 0%; }
  .status-text { font-size: 13px; color: var(--muted); min-height: 20px; }

  /* Summary cards */
  .summary-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .summary-stat {
    background: var(--bg); border-radius: 8px; padding: 14px;
  }
  .summary-stat .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .summary-stat .stat-value { font-size: 24px; font-weight: 700; }
  .summary-stat .stat-value.green { color: var(--green); }
  .summary-stat .stat-value.blue { color: var(--blue); }
  .summary-stat .stat-value.purple { color: var(--purple); }

  /* Vendor breakdown */
  .vendor-breakdown { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin-bottom: 20px; }
  .vendor-stat {
    display: flex; justify-content: space-between; align-items: center;
    background: var(--bg); border-radius: 8px; padding: 10px 14px;
  }
  .vendor-stat .name { font-size: 13px; }
  .vendor-stat .count { font-size: 14px; font-weight: 700; color: var(--blue); }
  .vendor-stat .error { font-size: 12px; color: var(--red); }

  /* Results table */
  .table-controls { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .search-input { max-width: 300px; }
  .filter-select {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 12px; color: var(--text); font-size: 13px; outline: none;
  }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
    color: var(--muted); font-weight: 600; padding: 10px 14px;
    border-bottom: 1px solid var(--border); cursor: pointer; user-select: none;
    white-space: nowrap;
  }
  thead th:hover { color: var(--text); }
  thead th.sorted { color: var(--blue); }
  thead th .sort-arrow { margin-left: 4px; font-size: 10px; }
  tbody td { padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border); }
  tbody tr:hover { background: var(--surface-hover); }
  tbody td a { color: var(--blue); text-decoration: none; }
  tbody td a:hover { text-decoration: underline; }
  .vendor-badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px;
    font-weight: 600; background: var(--blue-dim); color: var(--blue);
  }
  .no-results { text-align: center; padding: 40px; color: var(--muted); }

  /* Lookup section */
  .lookup-row { display: flex; gap: 10px; align-items: flex-end; }
  .lookup-row input { max-width: 400px; }
  .lookup-result { margin-top: 16px; font-size: 14px; }
  .lookup-result .found { color: var(--green); }
  .lookup-result .not-found { color: var(--muted); }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .grid-2 > .card { margin-bottom: 0; }
  @media (max-width: 800px) { .grid-2 { grid-template-columns: 1fr; } }

  .hidden { display: none !important; }
  .pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 16px; }
  .pagination .btn { padding: 6px 12px; font-size: 12px; }
  .page-info { font-size: 13px; color: var(--muted); }
</style>
</head>
<body>

<header>
  <h1>Streaming Finder</h1>
  <span class="subtitle">Find websites using live streaming vendors via BuiltWith</span>
</header>

<!-- Search Card -->
<div class="card">
  <h2>Search Vendors</h2>
  <div class="vendor-grid" id="vendorGrid"></div>
  <div class="btn-row">
    <button class="btn btn-ghost" onclick="toggleAllVendors()">Select All / None</button>
    <div style="flex:1"></div>
    <div class="control-group" style="flex-direction:row; align-items:center; gap:8px;">
      <label style="margin:0">Limit per vendor:</label>
      <input type="number" id="limitInput" value="50" min="1" max="500" style="width:80px">
    </div>
    <button class="btn btn-primary" id="searchBtn" onclick="runSearch()">Search</button>
  </div>
  <div class="progress-bar" id="progressBar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="status-text" id="statusText"></div>
</div>

<!-- Results -->
<div id="resultsSection" class="hidden">

  <!-- Summary -->
  <div class="card">
    <h2>Summary</h2>
    <div class="summary-row" id="summaryRow"></div>
    <div class="vendor-breakdown" id="vendorBreakdown"></div>
  </div>

  <!-- Table -->
  <div class="card">
    <h2>Results</h2>
    <div class="table-controls">
      <input type="text" class="search-input" id="tableSearch" placeholder="Filter domains..." oninput="filterTable()">
      <select class="filter-select" id="vendorFilter" onchange="filterTable()">
        <option value="">All Vendors</option>
      </select>
      <div style="flex:1"></div>
      <button class="btn btn-secondary" onclick="exportCSV()">Export CSV</button>
    </div>
    <div id="tableContainer"></div>
    <div class="pagination" id="pagination"></div>
  </div>
</div>

<!-- Lookup Card -->
<div class="card">
  <h2>Domain Lookup</h2>
  <p style="font-size:13px; color:var(--muted); margin-bottom:12px;">Check which streaming vendors a specific domain uses.</p>
  <div class="lookup-row">
    <input type="text" id="lookupInput" placeholder="e.g. twitch.tv" onkeydown="if(event.key==='Enter')lookupDomain()">
    <button class="btn btn-primary" id="lookupBtn" onclick="lookupDomain()">Lookup</button>
  </div>
  <div class="lookup-result" id="lookupResult"></div>
</div>

<script>
const VENDORS = __VENDORS_JSON__;
const PAGE_SIZE = 50;

let allResults = [];
let filteredResults = [];
let currentPage = 1;
let sortCol = null;
let sortAsc = true;
let selectedVendors = new Set(VENDORS.map(v => v.name));

// Build vendor grid
const grid = document.getElementById('vendorGrid');
VENDORS.forEach(v => {
  const chip = document.createElement('div');
  chip.className = 'vendor-chip selected';
  chip.dataset.vendor = v.name;
  chip.innerHTML = `<span class="check"></span>${v.name}`;
  chip.onclick = () => {
    chip.classList.toggle('selected');
    if (chip.classList.contains('selected')) selectedVendors.add(v.name);
    else selectedVendors.delete(v.name);
  };
  grid.appendChild(chip);
});

function toggleAllVendors() {
  const allSelected = selectedVendors.size === VENDORS.length;
  document.querySelectorAll('.vendor-chip').forEach(chip => {
    if (allSelected) {
      chip.classList.remove('selected');
      selectedVendors.clear();
    } else {
      chip.classList.add('selected');
      selectedVendors.add(chip.dataset.vendor);
    }
  });
}

async function runSearch() {
  const vendors = [...selectedVendors];
  if (!vendors.length) { alert('Select at least one vendor'); return; }

  const limit = parseInt(document.getElementById('limitInput').value) || 50;
  const btn = document.getElementById('searchBtn');
  const bar = document.getElementById('progressBar');
  const fill = document.getElementById('progressFill');
  const status = document.getElementById('statusText');

  btn.disabled = true;
  btn.textContent = 'Searching...';
  bar.classList.add('active');
  fill.style.width = '30%';
  status.textContent = `Searching ${vendors.length} vendor(s)...`;

  try {
    const resp = await fetch('/api/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({vendors, limit}),
    });
    fill.style.width = '90%';

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    fill.style.width = '100%';
    allResults = data.sites;
    renderResults(data);
    status.textContent = `Found ${data.total} site(s) across ${data.vendors.length} vendor(s)`;
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Search';
    setTimeout(() => { bar.classList.remove('active'); fill.style.width = '0%'; }, 800);
  }
}

function renderResults(data) {
  document.getElementById('resultsSection').classList.remove('hidden');

  // Summary
  const totalSites = data.total;
  const vendorsSearched = data.vendors.length;
  const vendorsWithResults = data.vendors.filter(v => v.count > 0).length;
  const errors = data.vendors.filter(v => v.error).length;

  document.getElementById('summaryRow').innerHTML = `
    <div class="summary-stat"><div class="stat-label">Total Sites</div><div class="stat-value blue">${totalSites}</div></div>
    <div class="summary-stat"><div class="stat-label">Vendors Searched</div><div class="stat-value">${vendorsSearched}</div></div>
    <div class="summary-stat"><div class="stat-label">Vendors With Results</div><div class="stat-value green">${vendorsWithResults}</div></div>
    ${errors ? `<div class="summary-stat"><div class="stat-label">Errors</div><div class="stat-value" style="color:var(--red)">${errors}</div></div>` : ''}
  `;

  // Vendor breakdown
  const breakdown = document.getElementById('vendorBreakdown');
  breakdown.innerHTML = data.vendors.map(v => `
    <div class="vendor-stat">
      <span class="name">${v.vendor}</span>
      ${v.error ? `<span class="error" title="${v.error}">Error</span>` : `<span class="count">${v.count}</span>`}
    </div>
  `).join('');

  // Vendor filter dropdown
  const filter = document.getElementById('vendorFilter');
  filter.innerHTML = '<option value="">All Vendors</option>' +
    data.vendors.filter(v => v.count > 0).map(v => `<option value="${v.vendor}">${v.vendor} (${v.count})</option>`).join('');

  sortCol = null;
  currentPage = 1;
  filterTable();
}

function filterTable() {
  const search = document.getElementById('tableSearch').value.toLowerCase();
  const vendor = document.getElementById('vendorFilter').value;

  filteredResults = allResults.filter(r => {
    if (vendor && r.vendor !== vendor) return false;
    if (search && !r.domain.toLowerCase().includes(search)) return false;
    return true;
  });

  if (sortCol) {
    filteredResults.sort((a, b) => {
      let va = a[sortCol] || '', vb = b[sortCol] || '';
      if (sortCol === 'rank') { va = Number(va) || 0; vb = Number(vb) || 0; }
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    });
  }

  currentPage = 1;
  renderTable();
}

function setSort(col) {
  if (sortCol === col) sortAsc = !sortAsc;
  else { sortCol = col; sortAsc = true; }
  filterTable();
}

function renderTable() {
  const start = (currentPage - 1) * PAGE_SIZE;
  const page = filteredResults.slice(start, start + PAGE_SIZE);
  const totalPages = Math.ceil(filteredResults.length / PAGE_SIZE);

  const arrow = (col) => sortCol === col ? `<span class="sort-arrow">${sortAsc ? '\u25B2' : '\u25BC'}</span>` : '';
  const sorted = (col) => sortCol === col ? ' sorted' : '';

  const container = document.getElementById('tableContainer');
  if (!filteredResults.length) {
    container.innerHTML = '<div class="no-results">No results to display</div>';
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th class="${sorted('vendor')}" onclick="setSort('vendor')">Vendor${arrow('vendor')}</th>
          <th class="${sorted('domain')}" onclick="setSort('domain')">Domain${arrow('domain')}</th>
          <th class="${sorted('rank')}" onclick="setSort('rank')">Rank${arrow('rank')}</th>
          <th class="${sorted('first_detected')}" onclick="setSort('first_detected')">First Detected${arrow('first_detected')}</th>
          <th class="${sorted('last_detected')}" onclick="setSort('last_detected')">Last Detected${arrow('last_detected')}</th>
        </tr>
      </thead>
      <tbody>
        ${page.map(r => `
          <tr>
            <td><span class="vendor-badge">${r.vendor}</span></td>
            <td><a href="https://${r.domain}" target="_blank" rel="noopener">${r.domain}</a></td>
            <td>${r.rank || '-'}</td>
            <td>${r.first_detected || '-'}</td>
            <td>${r.last_detected || '-'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  const pagination = document.getElementById('pagination');
  if (totalPages <= 1) { pagination.innerHTML = ''; return; }
  pagination.innerHTML = `
    <button class="btn btn-secondary" ${currentPage <= 1 ? 'disabled' : ''} onclick="currentPage--;renderTable()">Prev</button>
    <span class="page-info">Page ${currentPage} of ${totalPages} (${filteredResults.length} results)</span>
    <button class="btn btn-secondary" ${currentPage >= totalPages ? 'disabled' : ''} onclick="currentPage++;renderTable()">Next</button>
  `;
}

async function exportCSV() {
  const data = filteredResults.length ? filteredResults : allResults;
  if (!data.length) return;

  const resp = await fetch('/api/export', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({sites: data}),
  });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'streaming_finder_results.csv';
  a.click();
  URL.revokeObjectURL(url);
}

async function lookupDomain() {
  const input = document.getElementById('lookupInput');
  const domain = input.value.trim();
  if (!domain) return;

  const btn = document.getElementById('lookupBtn');
  const result = document.getElementById('lookupResult');
  btn.disabled = true;
  btn.textContent = 'Looking up...';
  result.innerHTML = '';

  try {
    const resp = await fetch('/api/lookup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({domain}),
    });
    const data = await resp.json();
    if (data.error) {
      result.innerHTML = `<span style="color:var(--red)">${data.error}</span>`;
    } else if (data.vendors_found.length) {
      result.innerHTML = `<span class="found">Streaming vendors detected on <strong>${domain}</strong>: ${data.vendors_found.join(', ')}</span>`;
    } else {
      result.innerHTML = `<span class="not-found">No known streaming vendors detected on <strong>${domain}</strong>.</span>`;
    }
  } catch (e) {
    result.innerHTML = `<span style="color:var(--red)">Error: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Lookup';
  }
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run("streaming_finder_web:app", host="0.0.0.0", port=8001, reload=True)

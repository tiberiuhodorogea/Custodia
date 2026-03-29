/* ── State ──────────────────────────────────────────── */
let ws = null;
let reconnectTimer = null;
const logLines = [];        // all log entries {level, message, timestamp}
const MAX_LOG_LINES = 600;

/* ── Helpers ───────────────────────────────────────── */
function fmtBytes(n) {
  if (n == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
}

function fmtDuration(sec) {
  if (!sec || sec <= 0) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  return ts.replace('T', ' ').slice(0, 19);
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  return res.json();
}

/* ── WebSocket ─────────────────────────────────────── */
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('ws-status').className = 'ws-dot connected';
    document.getElementById('ws-label').textContent = 'Connected';
  };

  ws.onclose = () => {
    document.getElementById('ws-status').className = 'ws-dot disconnected';
    document.getElementById('ws-label').textContent = 'Reconnecting…';
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWS, 2000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'update') {
      renderState(msg.state);
      if (msg.logs && msg.logs.length) {
        msg.logs.forEach(l => pushLog(l));
        renderLogs();
      }
    }
  };
}

/* ── Render: Status card ───────────────────────────── */
function renderState(s) {
  const badge = document.getElementById('status-badge');
  const fill  = document.getElementById('progress-fill');

  // Badge
  let label = 'IDLE';
  let cls = '';
  if (s.running) {
    label = s.cancel_requested ? 'CANCELLING' : s.phase.toUpperCase();
    cls = 'running';
  }
  badge.textContent = label;
  badge.className = 'badge ' + cls;

  // Button / inline progress toggle
  const btnRun       = document.getElementById('btn-run');
  const backupActive = document.getElementById('backup-active');
  const pct = s.bytes_total > 0 ? (s.bytes_copied / s.bytes_total) * 100 : 0;

  if (s.running) {
    btnRun.style.display = 'none';
    backupActive.style.display = 'flex';
    const phases = { scanning: 'Scanning files…', copying: 'Copying…', cleaning: 'Cleaning up…' };
    document.getElementById('inline-phase').textContent =
      s.cancel_requested ? 'Cancelling…' : (phases[s.phase] || 'Running…');
    document.getElementById('inline-fill').style.width = pct.toFixed(1) + '%';
  } else {
    btnRun.style.display = '';
    backupActive.style.display = 'none';
  }

  // Stats — show live values while running, reset to dashes when idle
  if (s.running) {
    const eta = s.speed_bps > 0 && s.bytes_total > s.bytes_copied
      ? Math.round((s.bytes_total - s.bytes_copied) / s.speed_bps)
      : 0;
    fill.style.width = pct.toFixed(1) + '%';
    document.getElementById('stat-files').textContent   = `${s.files_copied} / ${s.files_total} files`;
    document.getElementById('stat-bytes').textContent   = `${fmtBytes(s.bytes_copied)} / ${fmtBytes(s.bytes_total)}`;
    document.getElementById('stat-speed').textContent   = s.speed_bps > 0 ? fmtBytes(s.speed_bps) + '/s' : '—';
    document.getElementById('stat-elapsed').textContent = fmtDuration(s.elapsed_seconds);
    document.getElementById('stat-eta').textContent     = eta > 0 ? 'ETA ' + fmtDuration(eta) : '—';
    document.getElementById('current-file').textContent = s.current_file || '\u00A0';
  } else {
    fill.style.width = '0%';
    document.getElementById('stat-files').textContent   = '—';
    document.getElementById('stat-bytes').textContent   = '—';
    document.getElementById('stat-speed').textContent   = '—';
    document.getElementById('stat-elapsed').textContent = '—';
    document.getElementById('stat-eta').textContent     = '—';
    document.getElementById('current-file').textContent = '\u00A0';
  }

  // Meta
  if (s.last_run_time) document.getElementById('last-run').textContent = fmtTime(s.last_run_time);
  document.getElementById('next-run').textContent = s.next_scheduled ? fmtTime(s.next_scheduled) : '—';
}

/* ── Render: Sources & Destinations ────────────────── */
function renderPathList(items, elId, type) {
  const ul = document.getElementById(elId);
  if (!items.length) {
    ul.innerHTML = '<li class="empty-msg">None configured.</li>';
    return;
  }
  ul.innerHTML = items.map(it => `
    <li class="${it.enabled ? '' : 'disabled'}">
      <button class="toggle-sm ${it.enabled ? 'on' : ''}"
              onclick="${type}Toggle(${it.id}, ${it.enabled ? 'false' : 'true'})"></button>
      <span class="path-label">${esc(it.label)}</span>
      <span class="path-value" title="${esc(it.path)}">${esc(it.path)}</span>
      <span class="path-actions">
        <button class="icon-btn" onclick="${type}Remove(${it.id})" title="Remove">&times;</button>
      </span>
    </li>
  `).join('');
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function loadSources()  { renderPathList(await api('GET', '/api/sources'),      'source-list', 'src'); }
async function loadDests()    { renderPathList(await api('GET', '/api/destinations'),  'dest-list',   'dst'); }

/* ── Folder browser modal ──────────────────────────── */
let _browseMode    = null;  // 'source' | 'dest'
let _browseCurrent = '';

window.browseSource = () => { _browseMode = 'source'; _openBrowse(); };
window.browseDest   = () => { _browseMode = 'dest';   _openBrowse(); };

function _openBrowse() {
  _showBrowseModal(true);
  _browseTo('');
}

function _showBrowseModal(visible) {
  document.getElementById('browse-overlay').style.display = visible ? 'block' : 'none';
  document.getElementById('browse-modal').style.display   = visible ? 'flex'  : 'none';
}

window.closeBrowseModal = () => _showBrowseModal(false);

window.confirmBrowse = async function() {
  if (_browseCurrent) {
    if (_browseMode === 'source') {
      await api('POST', '/api/sources', { path: _browseCurrent, label: '' });
      loadSources();
    } else if (_browseMode === 'dest') {
      await api('POST', '/api/destinations', { path: _browseCurrent, label: '' });
      loadDests();
    }
  }
  _showBrowseModal(false);
};

async function _browseTo(path) {
  const url = '/api/browse' + (path ? '?path=' + encodeURIComponent(path) : '');
  const res  = await fetch(url).then(r => r.json());
  _browseCurrent = res.path;

  document.getElementById('browse-path').textContent = res.path || 'Select a drive';

  const list = document.getElementById('browse-list');
  list.innerHTML = '';

  if (res.parent !== null && res.parent !== undefined) {
    const li = document.createElement('li');
    li.className = 'browse-item browse-up';
    li.textContent = '↑ ..';
    li.dataset.path = res.parent;
    list.appendChild(li);
  }

  if (!res.entries || res.entries.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty-msg';
    li.style.padding = '.75rem';
    li.textContent = 'No subfolders';
    list.appendChild(li);
  } else {
    res.entries.forEach(e => {
      const li = document.createElement('li');
      li.className = 'browse-item';
      li.textContent = e.name;
      li.dataset.path = e.path;
      list.appendChild(li);
    });
  }
}

// Single delegated listener — no inline onclick, no escaping issues
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('browse-list').addEventListener('click', e => {
    const li = e.target.closest('.browse-item');
    if (li && li.dataset.path !== undefined) _browseTo(li.dataset.path);
  });
});


/* global */ window.srcToggle = async (id, en) => { await api('PATCH', `/api/sources/${id}`, { enabled: en }); loadSources(); };
/* global */ window.srcRemove = async (id) => { await api('DELETE', `/api/sources/${id}`); loadSources(); };
/* global */ window.dstToggle = async (id, en) => { await api('PATCH', `/api/destinations/${id}`, { enabled: en }); loadDests(); };
/* global */ window.dstRemove = async (id) => { await api('DELETE', `/api/destinations/${id}`); loadDests(); };

/* ── Settings ──────────────────────────────────────── */
function _applySchedulerState() {
  const on = document.getElementById('set-enabled').checked;
  ['set-freq', 'set-hour', 'set-min', 'set-retention'].forEach(id => {
    document.getElementById(id).disabled = !on;
  });
}

async function loadSettings() {
  const s = await api('GET', '/api/settings');
  document.getElementById('set-freq').value      = s.frequency_days || 1;
  const [hh, mm] = (s.backup_time || '02:00').split(':');
  document.getElementById('set-hour').value      = parseInt(hh, 10);
  document.getElementById('set-min').value       = parseInt(mm, 10);
  document.getElementById('set-retention').value = s.retention_count || 3;
  document.getElementById('ret-val').textContent = s.retention_count || 3;
  document.getElementById('set-enabled').checked = s.scheduler_enabled === 'true';
  _applySchedulerState();
}

async function saveSettings() {
  const hh = String(parseInt(document.getElementById('set-hour').value, 10) || 0).padStart(2, '0');
  const mm = String(parseInt(document.getElementById('set-min').value,  10) || 0).padStart(2, '0');
  await api('PUT', '/api/settings', {
    frequency_days:    parseInt(document.getElementById('set-freq').value, 10),
    backup_time:       `${hh}:${mm}`,
    retention_count:   parseInt(document.getElementById('set-retention').value, 10),
    scheduler_enabled: document.getElementById('set-enabled').checked,
  });
}
window.saveSettings = saveSettings;

window.onSchedulerChange = function() {
  _applySchedulerState();
  saveSettings();
};

/* ── Backup control ────────────────────────────────── */
function _showRunning(phase) {
  document.getElementById('btn-run').style.display = 'none';
  document.getElementById('backup-active').style.display = 'flex';
  document.getElementById('inline-phase').textContent = phase || 'Starting…';
}
function _showIdle() {
  document.getElementById('btn-run').style.display = '';
  document.getElementById('backup-active').style.display = 'none';
}

async function startBackup() {
  _showRunning('Starting…');
  const res = await api('POST', '/api/backup/start');
  if (res && res.ok === false) _showIdle(); // failed to start — revert
}
async function cancelBackup() { await api('POST', '/api/backup/cancel'); }
window.startBackup  = startBackup;
window.cancelBackup = cancelBackup;

/* ── History ───────────────────────────────────────── */
async function loadHistory() {
  const runs = await api('GET', '/api/history?limit=20');
  const tbody = document.querySelector('#history-table tbody');
  const empty = document.getElementById('history-empty');
  if (!runs.length) { tbody.innerHTML = ''; empty.style.display = ''; return; }
  empty.style.display = 'none';
  tbody.innerHTML = runs.map(r => {
    let dur = '—';
    if (r.started_at && r.completed_at) {
      const d = (new Date(r.completed_at) - new Date(r.started_at)) / 1000;
      dur = fmtDuration(d);
    }
    return `<tr>
      <td>${fmtTime(r.started_at)}</td>
      <td><span class="status-pill ${r.status}">${r.status.replace(/_/g,' ')}</span></td>
      <td>${r.files_copied} / ${r.files_total}</td>
      <td>${fmtBytes(r.bytes_copied)}</td>
      <td>${r.files_skipped || 0}</td>
      <td>${r.files_failed || 0}</td>
      <td>${dur}</td>
    </tr>`;
  }).join('');
}

/* ── Logs ──────────────────────────────────────────── */
function pushLog(entry) {
  logLines.push(entry);
  if (logLines.length > MAX_LOG_LINES) logLines.shift();
}

function renderLogs() {
  const viewer = document.getElementById('log-viewer');
  const filter = document.getElementById('log-filter').value;
  const wasAtBottom = viewer.scrollTop + viewer.clientHeight >= viewer.scrollHeight - 30;

  // only append new lines
  const existing = viewer.children.length;
  const start = Math.max(0, logLines.length - MAX_LOG_LINES);
  for (let i = existing; i < logLines.length; i++) {
    const l = logLines[i];
    const div = document.createElement('div');
    div.className = 'log-line' + (filter !== 'all' && l.level !== filter ? ' hidden' : '');
    div.dataset.level = l.level;
    div.innerHTML = `<span class="log-ts">${esc(l.timestamp)}</span><span class="log-lvl ${l.level}">${l.level}</span><span class="log-msg">${esc(l.message)}</span>`;
    viewer.appendChild(div);
  }

  if (wasAtBottom) viewer.scrollTop = viewer.scrollHeight;
}

function applyLogFilter() {
  const filter = document.getElementById('log-filter').value;
  document.querySelectorAll('.log-line').forEach(el => {
    el.classList.toggle('hidden', filter !== 'all' && el.dataset.level !== filter);
  });
}
window.applyLogFilter = applyLogFilter;

function clearLogs() {
  logLines.length = 0;
  document.getElementById('log-viewer').innerHTML = '';
}
window.clearLogs = clearLogs;

/* ── Periodic refresh for history ──────────────────── */
setInterval(loadHistory, 10000);

/* ── Init ──────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadSources();
  loadDests();
  loadSettings();
  loadHistory();
  connectWS();
});

/* Room Sync — Main application logic.
 *
 * Fetches data from the static JSON files served by GitHub Pages,
 * renders the dashboard, creation matrix, and decommission UI.
 */

// Data base URL — relative to the Pages site
const DATA_BASE = 'data';

let mappingData = null;
let pendingData = null;
let changelogData = null;
let locationsData = null;

// Track rooms approved in this session so they're hidden immediately.
// Stored as Sets of "platform:id" strings (e.g. "neat:1825", "zoom:abc123").
function getApprovedIds() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem('approved_ids') || '[]'));
  } catch { return new Set(); }
}

function markApproved(sourceId, targetId, targetPlatform) {
  const ids = getApprovedIds();
  ids.add(`zoom:${sourceId}`);
  ids.add(`${targetPlatform}:${targetId}`);
  sessionStorage.setItem('approved_ids', JSON.stringify([...ids]));
}

// -- Data loading -------------------------------------------------------

async function fetchJSON(path) {
  try {
    const resp = await fetch(`${DATA_BASE}/${path}?_=${Date.now()}`);
    if (!resp.ok) return null;
    return await resp.json();
  } catch (e) {
    console.error(`Failed to fetch ${path}:`, e);
    return null;
  }
}

async function loadAllData() {
  [mappingData, pendingData, changelogData, locationsData] = await Promise.all([
    fetchJSON('mapping.json'),
    fetchJSON('pending.json'),
    fetchJSON('changelog.json'),
    fetchJSON('locations.json'),
  ]);
}

// -- Dashboard ----------------------------------------------------------

function renderDashboard() {
  if (!mappingData) return;

  // Last sync
  const lastSync = document.getElementById('last-sync');
  if (lastSync) {
    lastSync.textContent = mappingData.last_sync
      ? `Last sync: ${new Date(mappingData.last_sync).toLocaleString()}`
      : 'No sync has run yet';
  }

  // Summary cards
  const rooms = mappingData.rooms || {};
  const roomCount = Object.keys(rooms).length;
  const unmappedCount = (mappingData.unmapped_zoom || []).length
    + (mappingData.unmapped_neat || []).length
    + (mappingData.unmapped_xyte || []).length;
  const pendingCount = pendingData
    ? (pendingData.suggestions || []).length + (pendingData.discrepancies || []).length
    : 0;

  // Changes today
  const today = new Date().toISOString().slice(0, 10);
  const todayChanges = (changelogData || []).filter(
    e => e.timestamp && e.timestamp.startsWith(today)
  ).length;

  setCard('total-rooms', roomCount);
  setCard('unmapped-count', unmappedCount);
  setCard('pending-count', pendingCount);
  setCard('changes-today', todayChanges);

  // Style cards with warnings
  const unmappedCard = document.getElementById('unmapped-count');
  if (unmappedCard && unmappedCount > 0) unmappedCard.closest('.card').classList.add('warn');
  const pendingCard = document.getElementById('pending-count');
  if (pendingCard && pendingCount > 0) pendingCard.closest('.card').classList.add('warn');

  // Changelog
  renderChangelog();

  // Discrepancies
  renderDiscrepancies();

  // Suggestions
  renderSuggestions();

  // Unmapped lists
  renderUnmapped();
}

function setCard(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderChangelog() {
  const body = document.getElementById('changelog-body');
  if (!body || !changelogData) return;

  const all = changelogData.slice().reverse();
  const recent = all.slice(0, 5);
  if (!recent.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty">No changes recorded yet.</td></tr>';
    return;
  }

  body.innerHTML = recent.map(e => `
    <tr>
      <td>${formatTime(e.timestamp)}</td>
      <td><span class="badge ${actionBadge(e.action)}">${e.action.replace(/_/g, ' ')}</span></td>
      <td>${esc(e.room_name || '-')}</td>
      <td>${esc(e.details || '')}</td>
    </tr>
  `).join('');

  // Download full log link
  if (all.length > 5) {
    const wrapper = body.closest('table')?.parentElement;
    if (wrapper && !document.getElementById('download-log-link')) {
      wrapper.insertAdjacentHTML('afterend',
        `<p id="download-log-link" style="margin-top:8px;">
          Showing 5 of ${all.length} entries.
          <a href="#" onclick="downloadFullLog(); return false;" style="color:#2980b9;">Download full log (CSV)</a>
        </p>`);
    }
  }
}

function downloadFullLog() {
  if (!changelogData || !changelogData.length) return;
  const header = 'Timestamp,Action,Room Name,Details';
  const rows = changelogData.slice().reverse().map(e => {
    const ts = e.timestamp || '';
    const action = (e.action || '').replace(/_/g, ' ');
    const name = csvEsc(e.room_name || '');
    const details = csvEsc(e.details || '');
    return `${ts},${action},${name},${details}`;
  });
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `room-sync-changelog-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function csvEsc(s) {
  if (s == null) return '';
  s = String(s);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

function renderDiscrepancies() {
  const body = document.getElementById('discrepancies-body');
  if (!body || !pendingData) return;

  const discs = pendingData.discrepancies || [];
  if (!discs.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty">No discrepancies found.</td></tr>';
    return;
  }

  body.innerHTML = discs.map((d, i) => `
    <tr>
      <td>${esc(d.canonical_name)}</td>
      <td><span class="badge ${d.platform === 'neat' ? 'pending' : 'mismatch'}">${esc(d.platform)}</span></td>
      <td>${esc(d.platform_name)}</td>
      <td>
        ${isAuthenticated()
          ? `<button class="btn btn-primary" onclick="approveDiscrepancy(${i})">Fix Name</button>`
          : '<span style="color: #999;">Sign in to fix</span>'}
      </td>
    </tr>
  `).join('');
}

function renderSuggestions() {
  const body = document.getElementById('suggestions-body');
  if (!body || !pendingData) return;

  const allSugs = pendingData.suggestions || [];
  const approved = getApprovedIds();

  // Filter out suggestions where the source or best match has been approved
  const sugs = allSugs.filter(s => {
    if (approved.has(`zoom:${s.source_id}`)) return false;
    // Also hide if all matches for this suggestion have been approved
    const remaining = (s.matches || []).filter(m => !approved.has(`${m.platform}:${m.id}`));
    return remaining.length > 0;
  });

  // Progress counter
  const headerEl = document.querySelector('#suggestions-table')?.previousElementSibling?.previousElementSibling;
  const counterEl = document.getElementById('suggestions-counter');
  const approvedCount = allSugs.length - sugs.length;
  const counterHtml = `<span id="suggestions-counter" style="font-size:14px; color:#777; font-weight:normal; margin-left:12px;">${sugs.length} remaining${approvedCount > 0 ? ` (${approvedCount} approved this session)` : ''}</span>`;
  if (counterEl) {
    counterEl.outerHTML = counterHtml;
  } else {
    const h2 = document.querySelector('#suggestions-table')?.closest('.content')?.querySelector('h2:nth-of-type(3)');
    if (h2) h2.insertAdjacentHTML('beforeend', counterHtml);
  }

  if (!sugs.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">No suggestions remaining.</td></tr>';
    return;
  }

  const rows = [];
  for (const s of sugs) {
    const matches = (s.matches || []).filter(m => !approved.has(`${m.platform}:${m.id}`));
    for (const m of matches) {
      rows.push(`
        <tr data-source="${esc(s.source_id)}" data-target="${esc(m.platform)}:${esc(m.id)}">
          <td>${esc(s.source_name)}</td>
          <td>${esc(m.name)}</td>
          <td><span class="badge pending">${esc(m.platform)}</span></td>
          <td>
            <span class="score-bar"><span class="score-bar-fill" style="width:${m.score * 100}%"></span></span>
            ${Math.round(m.score * 100)}%
          </td>
          <td>
            ${isAuthenticated()
              ? `<button class="btn btn-primary" onclick="acceptSuggestion('${esc(s.source_id)}','${esc(m.id)}','${esc(m.platform)}')">Accept</button>`
              : '<span style="color: #999;">Sign in</span>'}
          </td>
        </tr>
      `);
    }
  }

  body.innerHTML = rows.length ? rows.join('') : '<tr><td colspan="5" class="empty">No suggestions remaining.</td></tr>';
}

function renderUnmapped() {
  renderList('unmapped-zoom', mappingData ? mappingData.unmapped_zoom : []);
  renderList('unmapped-neat', mappingData ? mappingData.unmapped_neat : []);
  renderList('unmapped-xyte', mappingData ? mappingData.unmapped_xyte : []);
}

function renderList(id, items) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<li class="empty">None</li>';
    return;
  }
  el.innerHTML = items.map(r => `<li>${esc(r.name || r.id)}</li>`).join('');
}

// -- Create Rooms -------------------------------------------------------

let matrixRows = [];

function loadLocations() {
  const select = document.getElementById('location-select');
  if (!select || !locationsData) return;

  const locs = locationsData.locations || [];
  select.innerHTML = locs.length
    ? locs.map(l => `<option value="${esc(l.name)}">${esc(l.name)}</option>`).join('')
    : '<option value="">No locations configured</option>';
}

function addRoomsToMatrix() {
  const input = document.getElementById('room-input');
  if (!input) return;

  const names = input.value.split('\n').map(n => n.trim()).filter(Boolean);
  for (const name of names) {
    if (!matrixRows.find(r => r.name === name)) {
      matrixRows.push({ name, zoom: true, neat: true, xyte: true });
    }
  }

  input.value = '';
  renderMatrix();
}

function renderMatrix() {
  const body = document.getElementById('matrix-body');
  const submitBtn = document.getElementById('submit-create');
  if (!body) return;

  if (!matrixRows.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">No rooms added yet. Enter room names above.</td></tr>';
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  body.innerHTML = matrixRows.map((r, i) => `
    <tr>
      <td style="text-align: left;">${esc(r.name)}</td>
      <td><input type="checkbox" ${r.zoom ? 'checked' : ''} onchange="matrixRows[${i}].zoom=this.checked"></td>
      <td><input type="checkbox" ${r.neat ? 'checked' : ''} onchange="matrixRows[${i}].neat=this.checked"></td>
      <td><input type="checkbox" ${r.xyte ? 'checked' : ''} onchange="matrixRows[${i}].xyte=this.checked"></td>
      <td><button class="btn btn-outline" onclick="removeMatrixRow(${i})" style="padding:4px 10px;font-size:12px;">X</button></td>
    </tr>
  `).join('');

  if (submitBtn) submitBtn.disabled = !isAuthenticated();
}

function removeMatrixRow(index) {
  matrixRows.splice(index, 1);
  renderMatrix();
}

function submitCreate() {
  if (!isAuthenticated()) {
    alert('Please sign in with GitHub first.');
    return;
  }
  if (!matrixRows.length) return;

  const text = document.getElementById('create-modal-text');
  if (text) text.textContent = `Create ${matrixRows.length} room(s) across selected platforms?`;
  openModal('create-modal');
}

async function confirmCreate() {
  closeModal('create-modal');

  const location = (document.getElementById('location-select') || {}).value || '';
  const locConfig = (locationsData && locationsData.locations || []).find(l => l.name === location) || {};

  const payload = matrixRows.map(r => {
    const platforms = [];
    if (r.zoom) platforms.push('zoom');
    if (r.neat) platforms.push('neat');
    if (r.xyte) platforms.push('xyte');
    return {
      name: r.name,
      location: location,
      platforms: platforms,
      neat_location_id: locConfig.neat_location_id || '',
      xyte_building_space_id: locConfig.xyte_building_space_id || '',
    };
  });

  const ok = await dispatchWorkflow('create-rooms', payload);
  if (ok) {
    alert('Room creation workflow dispatched! Check the Actions tab for progress.');
    matrixRows = [];
    renderMatrix();
  }
}

// -- Decommission -------------------------------------------------------

let decomTarget = null;

function searchRooms() {
  const query = (document.getElementById('search-input') || {}).value || '';
  renderDecomRooms(query.trim().toLowerCase());
}

function renderDecomRooms(query) {
  const body = document.getElementById('rooms-body');
  if (!body || !mappingData) return;

  const rooms = Object.entries(mappingData.rooms || {});
  const filtered = query
    ? rooms.filter(([, r]) => r.canonical_name.toLowerCase().includes(query))
    : rooms;

  if (!filtered.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">No rooms found.</td></tr>';
    return;
  }

  body.innerHTML = filtered.map(([uid, r]) => `
    <tr>
      <td>${esc(r.canonical_name)}</td>
      <td>${r.zoom_room_id ? '<span class="badge synced">Yes</span>' : '<span class="badge missing">No</span>'}</td>
      <td>${r.neat_room_id ? '<span class="badge synced">Yes</span>' : '<span class="badge missing">No</span>'}</td>
      <td>${r.xyte_space_id ? '<span class="badge synced">Yes</span>' : '<span class="badge missing">No</span>'}</td>
      <td>
        ${isAuthenticated()
          ? `<button class="btn btn-danger" onclick="startDecommission('${esc(uid)}')">Decommission</button>`
          : '<span style="color: #999;">Sign in</span>'}
      </td>
    </tr>
  `).join('');
}

function startDecommission(uid) {
  if (!mappingData || !mappingData.rooms[uid]) return;
  decomTarget = { uid, name: mappingData.rooms[uid].canonical_name };

  const nameEl = document.getElementById('decom-room-name');
  if (nameEl) nameEl.textContent = decomTarget.name;

  const input = document.getElementById('decom-confirm-input');
  if (input) input.value = '';

  const btn = document.getElementById('decom-confirm-btn');
  if (btn) btn.disabled = true;

  openModal('decom-modal');
}

function validateDecomConfirm() {
  const input = document.getElementById('decom-confirm-input');
  const btn = document.getElementById('decom-confirm-btn');
  if (!input || !btn || !decomTarget) return;
  btn.disabled = input.value !== decomTarget.name;
}

async function confirmDecommission() {
  closeModal('decom-modal');
  if (!decomTarget) return;

  const payload = [{ uid: decomTarget.uid, confirmation_name: decomTarget.name }];
  const ok = await dispatchWorkflow('decommission', payload);
  if (ok) {
    alert('Decommission workflow dispatched! Check the Actions tab for progress.');
    decomTarget = null;
  }
}

// -- Actions (approve discrepancy, accept suggestion) -------------------

async function approveDiscrepancy(index) {
  if (!pendingData || !pendingData.discrepancies[index]) return;
  const d = pendingData.discrepancies[index];

  // Discrepancy fix = force the platform to match the canonical Zoom name.
  // This is done by triggering a nightly sync (which auto-renames known mappings).
  // For now, just dispatch a manual sync.
  const ok = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/nightly-sync.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        'Authorization': `token ${getToken()}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
    }
  );

  if (ok.status === 204) {
    alert('Sync workflow dispatched. The discrepancy will be resolved on the next run.');
  } else {
    alert('Failed to dispatch sync workflow.');
  }
}

async function triggerSync() {
  if (!isAuthenticated()) {
    alert('Please sign in with GitHub first.');
    return;
  }
  const btn = document.getElementById('sync-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Syncing...'; }

  const resp = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/nightly-sync.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        'Authorization': `token ${getToken()}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
    }
  );

  if (resp.status === 204) {
    if (btn) btn.textContent = 'Sync started';
    alert('Sync workflow dispatched. It takes about 6 minutes. Refresh the page afterwards to see updated data.');
  } else {
    if (btn) { btn.disabled = false; btn.textContent = 'Run Sync'; }
    alert('Failed to dispatch sync workflow.');
  }
}

async function acceptSuggestion(sourceId, targetId, targetPlatform) {
  const payload = [{
    zoom_id: sourceId,
    [targetPlatform === 'neat' ? 'neat_id' : 'xyte_space_id']: targetId,
  }];

  const ok = await dispatchWorkflow('approve-mapping', payload);
  if (ok) {
    // Mark as approved and immediately hide from the UI
    markApproved(sourceId, targetId, targetPlatform);
    renderSuggestions();
    // Update the pending count on the summary card
    updatePendingCard();
  }
}

function updatePendingCard() {
  if (!pendingData) return;
  const approved = getApprovedIds();
  const allSugs = pendingData.suggestions || [];
  const remaining = allSugs.filter(s => {
    if (approved.has(`zoom:${s.source_id}`)) return false;
    const rm = (s.matches || []).filter(m => !approved.has(`${m.platform}:${m.id}`));
    return rm.length > 0;
  });
  const discs = pendingData.discrepancies || [];
  setCard('pending-count', remaining.length + discs.length);
}

// -- Utilities ----------------------------------------------------------

function esc(s) {
  if (s == null) return '';
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}

function formatTime(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function actionBadge(action) {
  if (action === 'auto_rename') return 'synced';
  if (action === 'decommissioned') return 'missing';
  if (action === 'room_created') return 'synced';
  return 'pending';
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('active');
}

// -- Init ---------------------------------------------------------------

// Called by auth.js after org membership is verified.
// No data is fetched until this runs.
async function onAuthReady() {
  await loadAllData();

  // Dashboard
  if (document.getElementById('changelog-body')) {
    renderDashboard();
  }

  // Create page
  if (document.getElementById('matrix-body')) {
    loadLocations();
    renderMatrix();
  }

  // Decommission page
  if (document.getElementById('rooms-body')) {
    renderDecomRooms('');
  }
}

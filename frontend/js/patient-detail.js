// One patient's real record: profile, active medications, conditions,
// interaction reports (generate/poll/view/PDF/QR/delete), care team, and
// transfer initiation — all against the real backend endpoints merged in
// from upstream/main's Phase C/D/E work. No demo fixture on this page.
renderWorkspaceShell('Patients');
const e = UI.escape;
const patientId = new URLSearchParams(location.search).get('id');
if (!patientId) {
  document.querySelector('.workspace-content').innerHTML = '<h1 class="workspace-heading">No patient selected</h1><a class="btn btn-primary" href="patients.html">Back to patients</a>';
  throw new Error('missing patient id');
}

let profile = null;

function fmtDate(d) { return d ? new Date(d).toLocaleDateString() : '—'; }

async function renderProfile() {
  const card = document.getElementById('profileCard');
  try {
    profile = await ApiClient.getPatient(patientId);
    UI.text('pageHeading', profile.legal_name);
    UI.text('pageSubhead', 'Age ' + profile.age + ' · ' + profile.biological_sex);
    card.innerHTML = `
      <header class="ws-card-header"><h2>Profile</h2></header>
      <div class="detail-rows">
        <div class="detail-row"><span class="detail-term">Date of birth</span><span class="detail-value">${e(fmtDate(profile.date_of_birth))}</span></div>
        <div class="detail-row"><span class="detail-term">Medical record number</span><span class="detail-value">${e(profile.medical_record_number)}</span></div>
        <div class="detail-row"><span class="detail-term">Emergency contact</span><span class="detail-value">${e(profile.emergency_contact || 'Not on file')}</span></div>
      </div>`;
  } catch (err) {
    card.innerHTML = '<p class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</p>';
  }
}

// --- Active medications -------------------------------------------------
async function renderRegimens() {
  const list = document.getElementById('regimenList');
  try {
    const regimens = await ApiClient.getPatientRegimens(patientId, true);
    UI.text('regimensNote', regimens.length + ' active');
    list.innerHTML = regimens.length ? regimens.map((r) => `
      <li class="medicine-item">
        <span class="medicine-info"><span class="medicine-name">${e(r.drug_name)}</span><br>
        <span class="medicine-detail">${e(r.dosage || 'Dose not entered')} · since ${e(fmtDate(r.start_date))}</span></span>
        <button class="medicine-view3d" type="button" data-discontinue="${e(r.id)}">Discontinue</button>
      </li>`).join('') : '<li class="empty-state">No active medications on record.</li>';
  } catch (err) {
    list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>';
  }
}
document.getElementById('regimenList').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-discontinue]');
  if (!btn) return;
  if (!confirm('Discontinue this medication? This preserves history (sets an end date) rather than deleting the record.')) return;
  try {
    await ApiClient.updateRegimen(patientId, btn.dataset.discontinue, { end_date: new Date().toISOString().slice(0, 10) });
    UI.announce('Medication discontinued.');
    renderRegimens();
  } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
});

function addRegimenForm() {
  const d = UI.modal('Add medication', `
    <form id="regimenForm">
      <label class="field-label" for="regSearch">Search the model's drug list</label>
      <input class="field-box" id="regSearch" autocomplete="off" placeholder="Start typing a drug name…">
      <ul id="regResults" class="candidate-list" style="max-height:200px;overflow-y:auto;margin-top:8px"></ul>
      <label class="field-label" for="regDose">Dosage</label>
      <input class="field-box" id="regDose" maxlength="60">
      <label class="field-label" for="regStart">Start date</label>
      <input class="field-box" id="regStart" type="date" required value="${new Date().toISOString().slice(0, 10)}">
      <p class="field-note">Only drugs the model was trained on can be added.</p>
      <p id="regimenError" role="alert"></p>
      <button class="btn btn-primary" type="submit" id="regimenSubmit" disabled>Add medication</button>
    </form>`);
  const input = document.getElementById('regSearch'), results = document.getElementById('regResults'), submit = document.getElementById('regimenSubmit');
  let selected = null, token = 0, debounce = null;
  async function search(q) {
    const my = ++token;
    if (!q || q.trim().length < 2) { results.innerHTML = ''; return; }
    let hits;
    try { hits = await ApiClient.searchDrugs(q.trim(), 20, 0); } catch (err) { if (my === token) results.innerHTML = '<li class="empty-state">' + e(err.message) + '</li>'; return; }
    if (my !== token) return;
    results.innerHTML = hits.length ? hits.map((h) => `<li><button type="button" class="candidate-row" data-cid="${e(h.cid)}" data-name="${e(h.name)}">${e(h.name)}</button></li>`).join('') : '<li class="empty-state">No match in the model\'s vocabulary.</li>';
  }
  input.addEventListener('input', () => { selected = null; submit.disabled = true; clearTimeout(debounce); debounce = setTimeout(() => search(input.value), 250); });
  results.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-cid]'); if (!b) return;
    selected = { cid: b.dataset.cid, name: b.dataset.name };
    input.value = b.dataset.name; results.innerHTML = ''; submit.disabled = false;
  });
  document.getElementById('regimenForm').onsubmit = async (ev) => {
    ev.preventDefault();
    if (!selected) { UI.text('regimenError', 'Pick a drug from the search results first.'); return; }
    try {
      await ApiClient.addRegimen(patientId, { drug_name: selected.name, pubchem_cid: selected.cid, dosage: document.getElementById('regDose').value || null, start_date: document.getElementById('regStart').value });
      d.close(); UI.announce('Medication added.'); renderRegimens();
    } catch (err) { UI.text('regimenError', ApiClient.getErrorMessage(err)); }
  };
  input.focus();
}
document.getElementById('addRegimenBtn').onclick = addRegimenForm;

// --- Conditions ----------------------------------------------------------
async function renderConditions() {
  const list = document.getElementById('conditionList');
  try {
    const conditions = await ApiClient.getPatientConditions(patientId);
    list.innerHTML = conditions.length ? conditions.map((c) => `
      <li class="medicine-item"><span class="medicine-info"><span class="medicine-name">${e(c.condition_name)}</span><br>
      <span class="medicine-detail">${e(c.icd10_code || 'No ICD-10 code')} · ${c.is_active ? 'Active' : 'Resolved'}</span></span></li>`).join('') : '<li class="empty-state">No conditions on record.</li>';
  } catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; }
}
document.getElementById('addConditionBtn').onclick = () => {
  const d = UI.modal('Add condition', `
    <form id="conditionForm">
      <label class="field-label" for="condName">Condition</label>
      <input class="field-box" id="condName" required maxlength="255">
      <label class="field-label" for="condIcd">ICD-10 code (optional)</label>
      <input class="field-box" id="condIcd" maxlength="16">
      <p id="conditionError" role="alert"></p>
      <button class="btn btn-primary" type="submit">Add condition</button>
    </form>`);
  document.getElementById('conditionForm').onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await ApiClient.addCondition(patientId, { condition_name: document.getElementById('condName').value, icd10_code: document.getElementById('condIcd').value || null });
      d.close(); UI.announce('Condition added.'); renderConditions();
    } catch (err) { UI.text('conditionError', ApiClient.getErrorMessage(err)); }
  };
};

// --- Reports ---------------------------------------------------------------
let pollTimer = null;
async function renderReports() {
  const list = document.getElementById('reportList');
  try {
    const reports = await ApiClient.getReports(patientId, 50, 0);
    UI.text('reportsNote', reports.length + ' report' + (reports.length === 1 ? '' : 's'));
    list.innerHTML = reports.length ? reports.map((r) => `
      <li class="medicine-item" style="flex-wrap:wrap">
        <span class="medicine-info"><span class="medicine-name">${e(fmtDate(r.created_at))} — ${e(r.status)}</span><br>
        <span class="medicine-detail">${r.summary ? r.summary.drug_count + ' drugs · ' + r.summary.high_risk_pair_count + ' high-risk pair(s) · toxicity ' + Math.round(r.summary.regimen_toxicity_index) : 'Pending…'}</span></span>
        <button class="medicine-view3d" type="button" data-view-report="${e(r.id)}">View</button>
        ${r.file_available ? `<a class="medicine-view3d" href="#" data-pdf="${e(r.id)}">PDF</a>` : `<button class="medicine-view3d" type="button" data-pdf="${e(r.id)}">Regenerate PDF</button>`}
        <button class="medicine-view3d" type="button" data-qr="${e(r.id)}">QR</button>
        <button class="medicine-remove" type="button" data-delete-report="${e(r.id)}" aria-label="Delete report">×</button>
      </li>`).join('') : '<li class="empty-state">No reports yet.</li>';

    const stillPending = reports.some((r) => r.status === 'pending');
    if (stillPending && !pollTimer) pollTimer = setTimeout(() => { pollTimer = null; renderReports(); }, 2500);
  } catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; }
}

document.getElementById('generateReportBtn').onclick = async () => {
  const btn = document.getElementById('generateReportBtn');
  btn.disabled = true;
  try {
    await ApiClient.createReport(patientId);
    UI.text('reportGenerateNote', 'Generating — this can take up to a couple of minutes (several model calls per report). Refreshing automatically.');
    renderReports();
  } catch (err) {
    UI.text('reportGenerateNote', ApiClient.getErrorMessage(err));
  }
  btn.disabled = false;
};

document.getElementById('reportList').addEventListener('click', async (ev) => {
  const viewBtn = ev.target.closest('[data-view-report]');
  const pdfBtn = ev.target.closest('[data-pdf]');
  const qrBtn = ev.target.closest('[data-qr]');
  const delBtn = ev.target.closest('[data-delete-report]');

  if (viewBtn) {
    try {
      const r = await ApiClient.getReport(viewBtn.dataset.viewReport);
      const sev = (x) => x || '';
      const html = `
        <p class="ws-card-footnote" style="color:var(--ink);font-weight:600">${e(r.model_status?.warning || r.model_status ? JSON.stringify(r.model_status) : '')}</p>
        <p class="field-note" style="font-weight:700">${e(r.disclaimer || '')}</p>
        ${r.model_status ? `<p class="pill ${r.model_status.degraded_mode ? 'badge-warn' : 'pill-muted'}">${r.model_status.degraded_mode ? 'DEGRADED MODEL OUTPUT' : 'Model nominal'}</p>` : ''}
        <h3 class="node-section-title">Regimen at generation time</h3>
        <p class="node-section-text">${e((r.regimen_snapshot || []).map((m) => m.drug_name).join(' · ') || 'None recorded')}</p>
        ${r.unresolved_drugs && r.unresolved_drugs.length ? `<p class="field-note" style="color:#a33">⚠ Excluded from analysis (not in model vocabulary): ${e(r.unresolved_drugs.map((u) => u.drug_name).join(', '))}</p>` : ''}
        <h3 class="node-section-title">Pairwise interactions</h3>
        ${(r.pairwise || []).map((p) => `<div class="detail-row"><span class="detail-term">${e(p.drug_a_cid)} × ${e(p.drug_b_cid)}</span><span class="detail-value">${Math.round(p.top_risk_score)} — ${e(p.top_adverse_effect)}${p.is_high_risk ? ' ⚠' : ''}</span></div>`).join('') || '<p class="node-section-text">None.</p>'}`;
      UI.modal('Report — ' + fmtDate(r.created_at), html);
    } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    return;
  }
  if (pdfBtn) {
    pdfBtn.textContent = 'Loading…';
    try {
      const blob = await ApiClient.getReportPdfBlob(pdfBtn.dataset.pdf);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      renderReports();
    } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    return;
  }
  if (qrBtn) {
    try {
      const blob = await ApiClient.getReportQrBlob(qrBtn.dataset.qr);
      const url = URL.createObjectURL(blob);
      UI.modal('Report QR', '<img src="' + url + '" alt="QR code linking to this report" style="width:100%;max-width:280px;display:block;margin:0 auto">');
    } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    return;
  }
  if (delBtn) {
    if (!confirm('Delete this report? This also revokes QR access to it.')) return;
    try { await ApiClient.deleteReport(delBtn.dataset.deleteReport); UI.announce('Report deleted.'); renderReports(); }
    catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
  }
});

// --- Care team & transfer ----------------------------------------------
async function renderAccess() {
  const list = document.getElementById('accessList');
  try {
    const access = await ApiClient.getPatientAccess(patientId);
    list.innerHTML = access.map((a) => `<li class="medicine-item"><span class="medicine-info"><span class="medicine-name">${e(a.clinician_email)}</span><br><span class="medicine-detail">${a.is_primary ? 'Primary' : 'Secondary'} · since ${e(fmtDate(a.assigned_at))}</span></span></li>`).join('') || '<li class="empty-state">No one currently assigned.</li>';
  } catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; }
}
async function renderTransfers() {
  const list = document.getElementById('transferList');
  try {
    const all = await ApiClient.getTransfers(200, 0);
    const mine = all.filter((t) => t.patient_id === patientId);
    list.innerHTML = mine.length ? mine.map((t) => `
      <li class="medicine-item"><span class="medicine-info"><span class="medicine-name">To ${e(t.to_clinician.email)}</span><br>
      <span class="medicine-detail">${e(t.status)}</span></span>
      ${t.status === 'pending_patient_consent' || t.status === 'locked' ? `<button class="medicine-remove" type="button" data-cancel-transfer="${e(t.id)}" aria-label="Cancel">Cancel</button>` : ''}</li>`).join('') : '<li class="empty-state">No transfer requests for this patient.</li>';
  } catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; }
}
document.getElementById('transferList').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-cancel-transfer]'); if (!btn) return;
  try { await ApiClient.cancelTransfer(btn.dataset.cancelTransfer); UI.announce('Transfer cancelled.'); renderTransfers(); }
  catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
});
document.getElementById('initiateTransferBtn').onclick = () => {
  const d = UI.modal('Transfer to another clinician', `
    <form id="transferForm">
      <label class="field-label" for="toEmail">Receiving clinician's email</label>
      <input class="field-box" id="toEmail" type="email" required>
      <p class="field-note">The patient must consent via an emailed one-time code before access changes. You keep access during a grace period regardless of their decision.</p>
      <p id="transferError" role="alert"></p>
      <button class="btn btn-primary" type="submit">Send request</button>
    </form>`);
  document.getElementById('transferForm').onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await ApiClient.createTransfer(patientId, { to_clinician_email: document.getElementById('toEmail').value });
      d.close(); UI.announce('Transfer request sent — awaiting patient consent.'); renderTransfers();
    } catch (err) { UI.text('transferError', ApiClient.getErrorMessage(err)); }
  };
};

renderProfile(); renderRegimens(); renderConditions(); renderReports(); renderAccess(); renderTransfers();

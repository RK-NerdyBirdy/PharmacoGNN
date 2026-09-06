// There's no "list all my reports" endpoint -- reports are always scoped to
// one patient's regimen snapshot (GET /patients/{id}/reports). So this page
// does the honest thing for each role instead of fabricating a merged list:
//   - PATIENT: fetch their own profile id, show their own reports directly
//     (generation/delete are clinician-only per RBAC, so no generate button).
//   - CLINICIAN: no single call can list "reports across all my patients",
//     so this is a wayfinding list into each patient's own reports section
//     (already built in patient-detail.js) rather than an N+1 fetch loop.
renderWorkspaceShell('Reports');
const e = UI.escape;
const session = ApiClient.getSession();

function fmtDate(d) { return d ? new Date(d).toLocaleDateString() : '—'; }

async function renderPatientView() {
  UI.text('reportsCardTitle', 'My reports');
  const list = document.getElementById('reportList');
  let me;
  try { me = await ApiClient.getMyProfile(); }
  catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; return; }

  let reports;
  try { reports = await ApiClient.getReports(me.id, 50, 0); }
  catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; return; }

  UI.text('reportsNote', reports.length + ' report' + (reports.length === 1 ? '' : 's'));
  list.innerHTML = reports.length ? reports.map((r) => `
    <li class="medicine-item">
      <span class="medicine-info"><span class="medicine-name">${e(fmtDate(r.created_at))} — ${e(r.status)}</span><br>
      <span class="medicine-detail">${r.summary ? r.summary.drug_count + ' drugs · toxicity ' + Math.round(r.summary.regimen_toxicity_index) : 'Pending…'}</span></span>
      <button class="medicine-view3d" type="button" data-view="${e(r.id)}">View</button>
      ${r.file_available ? `<button class="medicine-view3d" type="button" data-pdf="${e(r.id)}">PDF</button>` : ''}
      <button class="medicine-view3d" type="button" data-qr="${e(r.id)}">QR</button>
    </li>`).join('') : '<li class="empty-state">No reports yet — ask your clinician to generate one.</li>';

  document.getElementById('reportList').addEventListener('click', async (ev) => {
    const viewBtn = ev.target.closest('[data-view]');
    const pdfBtn = ev.target.closest('[data-pdf]');
    const qrBtn = ev.target.closest('[data-qr]');
    if (viewBtn) {
      try {
        const r = await ApiClient.getReport(viewBtn.dataset.view);
        UI.modal('Report — ' + fmtDate(r.created_at), `
          <p class="field-note" style="font-weight:700">${e(r.disclaimer || '')}</p>
          ${r.model_status?.warning ? `<p class="pill badge-warn">${e(r.model_status.warning)}</p>` : ''}
          <h3 class="node-section-title">Regimen at generation time</h3>
          <p class="node-section-text">${e((r.regimen_snapshot || []).map((m) => m.drug_name).join(' · ') || 'None recorded')}</p>`);
      } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    } else if (pdfBtn) {
      try {
        const blob = await ApiClient.getReportPdfBlob(pdfBtn.dataset.pdf);
        const url = URL.createObjectURL(blob); window.open(url, '_blank'); setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    } else if (qrBtn) {
      try {
        const blob = await ApiClient.getReportQrBlob(qrBtn.dataset.qr);
        const url = URL.createObjectURL(blob);
        UI.modal('Report QR', '<img src="' + url + '" alt="QR code linking to this report" style="width:100%;max-width:280px;display:block;margin:0 auto">');
      } catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
    }
  }, { once: true });
}

async function renderClinicianView() {
  UI.text('reportsCardTitle', 'Reports by patient');
  UI.text('pageSubhead', 'Reports are generated per-patient — pick a patient to view, generate, or download theirs.');
  const list = document.getElementById('reportList');
  let patients;
  try { patients = await ApiClient.getPatientList(200, 0); }
  catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; return; }

  UI.text('reportsNote', patients.length + ' patient' + (patients.length === 1 ? '' : 's'));
  list.innerHTML = patients.length ? patients.map((p) => `
    <li class="medicine-item">
      <span class="medicine-info"><span class="medicine-name">${e(p.legal_name)}</span><br>
      <span class="medicine-detail">${p.active_regimen_count} active medication${p.active_regimen_count === 1 ? '' : 's'}</span></span>
      <a class="medicine-view3d" href="patient-detail.html?id=${e(p.id)}">View reports →</a>
    </li>`).join('') : '<li class="empty-state">No patients assigned yet.</li>';
}

if (session?.role === 'PATIENT') renderPatientView(); else renderClinicianView();

// Real clinician patient roster (GET /api/v1/patients), patient creation
// (POST /api/v1/patients — creates the account + profile + assignment +
// invite email server-side, no password ever handled here), and invite
// resend. Backed by real backend endpoints merged in from upstream/main's
// Phase C work — no demo fixture involved on this page.
renderWorkspaceShell('Patients');
const e = UI.escape;

async function render() {
  const list = document.getElementById('patientList');
  list.innerHTML = '<li class="empty-state">Loading patients…</li>';
  try {
    const patients = await ApiClient.getPatientList(200, 0);
    UI.text('rosterNote', patients.length + ' assigned patient' + (patients.length === 1 ? '' : 's'));
    list.innerHTML = patients.length ? patients.map((p) => `
      <li class="medicine-item">
        <span class="medicine-badge">${e((p.legal_name || '?')[0])}</span>
        <span class="medicine-info">
          <a class="medicine-name" href="patient-detail.html?id=${e(p.id)}">${e(p.legal_name)}</a><br>
          <span class="medicine-detail">Age ${p.age} · ${e(p.biological_sex)} · ${p.active_regimen_count} active med${p.active_regimen_count === 1 ? '' : 's'}</span>
        </span>
        <span class="pill ${p.activation_status === 'active' ? 'pill-muted' : 'badge-warn'}">${e(p.activation_status)}</span>
        ${p.activation_status !== 'active' ? `<button class="medicine-view3d" type="button" data-resend="${e(p.id)}">Resend invite</button>` : ''}
      </li>`).join('') : '<li class="empty-state">No patients assigned to you yet. Create one to get started.</li>';
  } catch (err) {
    list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>';
  }
}

document.getElementById('patientList').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-resend]');
  if (!btn) return;
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const r = await ApiClient.resendInvite(btn.dataset.resend);
    UI.announce('Invite ' + r.invite_email_status + '.');
  } catch (err) {
    UI.announce(ApiClient.getErrorMessage(err));
  }
  render();
});

function newPatientForm() {
  const d = UI.modal('New patient', `
    <form id="patientForm">
      <label class="field-label" for="pEmail">Email</label>
      <input class="field-box" id="pEmail" type="email" required>
      <label class="field-label" for="pName">Legal name</label>
      <input class="field-box" id="pName" required maxlength="255">
      <label class="field-label" for="pDob">Date of birth</label>
      <input class="field-box" id="pDob" type="date" required>
      <label class="field-label" for="pMrn">Medical record number</label>
      <input class="field-box" id="pMrn" required maxlength="255">
      <label class="field-label" for="pSex">Biological sex</label>
      <select class="field-box" id="pSex" required>
        <option value="FEMALE">Female</option><option value="MALE">Male</option><option value="INTERSEX">Intersex</option>
      </select>
      <label class="field-label" for="pAge">Age</label>
      <input class="field-box" id="pAge" type="number" min="0" max="130" required>
      <label class="field-label" for="pEmergency">Emergency contact (optional)</label>
      <input class="field-box" id="pEmergency" maxlength="255">
      <p class="field-note">No password is emailed — the patient sets their own via the invite link.</p>
      <p id="patientError" role="alert"></p>
      <button class="btn btn-primary" type="submit" id="patientSubmit">Create patient</button>
    </form>`);
  document.getElementById('patientForm').onsubmit = async (ev) => {
    ev.preventDefault();
    const submit = document.getElementById('patientSubmit');
    submit.disabled = true; submit.textContent = 'Creating…';
    try {
      const created = await ApiClient.createPatient({
        email: document.getElementById('pEmail').value,
        legal_name: document.getElementById('pName').value,
        date_of_birth: document.getElementById('pDob').value,
        medical_record_number: document.getElementById('pMrn').value,
        biological_sex: document.getElementById('pSex').value,
        age: Number(document.getElementById('pAge').value),
        emergency_contact: document.getElementById('pEmergency').value || null,
      });
      d.close();
      // Creation can succeed even when the invite email itself failed to
      // send — that's not a creation failure, just something to flag.
      UI.announce(created.invite_email_status === 'sent'
        ? 'Patient created. Invite email sent.'
        : 'Patient created. Invite email ' + created.invite_email_status + ' — use "Resend invite" if needed.');
      render();
    } catch (err) {
      UI.text('patientError', ApiClient.getErrorMessage(err));
      submit.disabled = false; submit.textContent = 'Create patient';
    }
  };
  document.getElementById('pEmail').focus();
}
document.getElementById('newPatientBtn').onclick = newPatientForm;

render();

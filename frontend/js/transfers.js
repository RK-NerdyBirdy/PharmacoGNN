// Real transfer requests (GET /api/v1/transfers), role-aware: a clinician
// sees both directions and can cancel one they initiated; a patient sees
// their own pending requests with OTP consent/decline/resend. Backed by the
// real transfers endpoints merged in from upstream/main — no demo fixture.
renderWorkspaceShell('Care transfers');
const e = UI.escape;
const session = ApiClient.getSession();
const role = session?.role;
const OPEN = new Set(['pending_patient_consent', 'locked']);

function statusLabel(s) {
  return { pending_patient_consent: 'Awaiting your consent', locked: 'Locked (too many attempts)', approved: 'Approved', declined: 'Declined', cancelled: 'Cancelled' }[s] || s;
}

function countdown(el, expiresAt) {
  function tick() {
    const ms = new Date(expiresAt).getTime() - Date.now();
    if (ms <= 0) { el.textContent = 'Code expired — request a new one.'; return; }
    const m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000);
    el.textContent = 'Code expires in ' + m + ':' + String(s).padStart(2, '0');
    setTimeout(tick, 1000);
  }
  tick();
}

async function render() {
  const list = document.getElementById('transferList');
  list.innerHTML = '<li class="empty-state">Loading…</li>';
  let transfers;
  try { transfers = await ApiClient.getTransfers(200, 0); }
  catch (err) { list.innerHTML = '<li class="empty-state">' + e(ApiClient.getErrorMessage(err)) + '</li>'; return; }

  UI.text('transfersNote', transfers.length + ' request' + (transfers.length === 1 ? '' : 's'));
  if (!transfers.length) { list.innerHTML = '<li class="empty-state">No transfer requests.</li>'; return; }

  list.innerHTML = transfers.map((t) => {
    const canCancel = role === 'CLINICIAN' && t.from_clinician.id === session.userId && OPEN.has(t.status);
    const canConsent = role === 'PATIENT' && OPEN.has(t.status);
    return `
    <li class="medicine-item" style="flex-direction:column;align-items:stretch;gap:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;width:100%">
        <span class="medicine-info"><span class="medicine-name">${e(t.from_clinician.email)} → ${e(t.to_clinician.email)}</span><br>
        <span class="medicine-detail">${e(statusLabel(t.status))}</span></span>
        ${canCancel ? `<button class="medicine-remove" type="button" data-cancel="${e(t.id)}">Cancel</button>` : ''}
      </div>
      ${canConsent ? `
      <form class="consent-form" data-consent-form="${e(t.id)}" style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
        <div>
          <label class="field-label" for="otp-${e(t.id)}">6-digit code (from email)</label>
          <input class="field-box" id="otp-${e(t.id)}" inputmode="numeric" pattern="\\d{6}" maxlength="6" ${t.status === 'locked' ? 'disabled' : 'required'} style="width:120px">
        </div>
        <button class="btn btn-primary" type="submit" ${t.status === 'locked' ? 'disabled' : ''}>Consent</button>
        <button class="btn btn-secondary" type="button" data-decline="${e(t.id)}">Decline</button>
        <button class="btn btn-outline" type="button" data-resend="${e(t.id)}">Resend code</button>
      </form>
      <p class="field-note" id="countdown-${e(t.id)}"></p>
      <p role="alert" id="consentError-${e(t.id)}"></p>` : ''}
    </li>`;
  }).join('');

  transfers.forEach((t) => {
    if (role === 'PATIENT' && OPEN.has(t.status) && t.status !== 'locked') {
      const el = document.getElementById('countdown-' + t.id);
      if (el) countdown(el, t.otp_expires_at);
    }
  });
}

document.getElementById('transferList').addEventListener('click', async (ev) => {
  const cancelBtn = ev.target.closest('[data-cancel]');
  const declineBtn = ev.target.closest('[data-decline]');
  const resendBtn = ev.target.closest('[data-resend]');
  if (cancelBtn) {
    try { await ApiClient.cancelTransfer(cancelBtn.dataset.cancel); UI.announce('Transfer cancelled.'); render(); }
    catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
  } else if (declineBtn) {
    if (!confirm('Decline this transfer request?')) return;
    try { await ApiClient.declineTransfer(declineBtn.dataset.decline); UI.announce('Transfer declined.'); render(); }
    catch (err) { UI.announce(ApiClient.getErrorMessage(err)); }
  } else if (resendBtn) {
    resendBtn.disabled = true;
    try { await ApiClient.resendTransferOtp(resendBtn.dataset.resend); UI.announce('A new code has been sent.'); render(); }
    catch (err) { UI.announce(ApiClient.getErrorMessage(err)); resendBtn.disabled = false; }
  }
});

document.getElementById('transferList').addEventListener('submit', async (ev) => {
  const form = ev.target.closest('[data-consent-form]');
  if (!form) return;
  ev.preventDefault();
  const id = form.dataset.consentForm;
  const otp = document.getElementById('otp-' + id).value;
  try {
    await ApiClient.consentTransfer(id, otp);
    UI.announce('Access granted to the receiving clinician.');
    render();
  } catch (err) {
    const errEl = document.getElementById('consentError-' + id);
    const msg = err.attemptsRemaining !== undefined ? ApiClient.getErrorMessage(err) + ' (' + err.attemptsRemaining + ' attempt' + (err.attemptsRemaining === 1 ? '' : 's') + ' remaining)' : ApiClient.getErrorMessage(err);
    if (errEl) errEl.textContent = msg; else UI.announce(msg);
    if (err.attemptsRemaining === 0) render(); // now locked server-side
  }
});

render();

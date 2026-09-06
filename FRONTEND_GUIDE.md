# PharmacoGNN — Frontend Integration Guide

Written for the frontend team building against the PharmacoGNN backend. Covers every user flow, the endpoints behind it, and the states the UI has to handle.

> **Read this first — build status.** Auth, patient management, the interaction workbench, prescription/regimen management, and reports are live; QR and transfers are not built yet. Every section is tagged:
>
> - 🟢 **LIVE** — built, tested, callable today
> - 🟡 **CHANGING** — exists today but its behavior/permissions are about to change; don't build against current behavior
> - 🔴 **PLANNED** — contract agreed, not implemented; mock it
>
> This document is the agreed contract, so you can build screens and mocks in parallel with backend work. Payload shapes for 🔴 endpoints are stable enough to code against; if one changes, that's on us to tell you.

For endpoints that are 🟢 today, [API_REFERENCE.md](API_REFERENCE.md) has the exhaustive field-level detail. This guide is flow-oriented and doesn't duplicate all of it.

---

## 1. Core concepts you must internalize

### Two roles, asymmetric power

| | `CLINICIAN` | `PATIENT` |
|---|---|---|
| Own profile | — | read + **limited** edit |
| Patient demographics | full edit (assigned patients) | edit name/age/email/emergency contact only |
| Conditions, regimens, prescriptions | full write | **read-only** |
| Reports | generate, view, delete | view own only |
| Transfers | initiate | consent/decline via OTP |

A patient can never write medical data. This is a regulatory constraint, not a preference — don't build UI that implies otherwise (no "add my medication" button, even disabled).

### Assignment, not just role

Being a clinician doesn't grant access to a patient. Access comes from an **assignment** between that specific clinician and that specific patient. A clinician sees only their assigned patients.

After a transfer (§9), a patient can have **more than one** clinician assigned at once — the original keeps access for a grace period. Build the "who has access" view accordingly; don't assume one.

### 404 means "not found *or* not yours"

Requesting a patient/report you aren't assigned to returns **`404`, not `403`** — deliberately, so the API doesn't leak that a given patient exists. Your error handling cannot distinguish the two cases and shouldn't try. Show one message: *"Not found, or you don't have access."*

### The model is currently unverified

Predictions are known to be inaccurate right now (the model scores nearly every drug interaction as high-risk). Until that's fixed:

- Every report carries a `disclaimer` string and a `model_status` object. **Both must be rendered prominently** — not in a collapsed panel, not in a footer. This is a patient-safety requirement.
- Prediction responses carry `degraded_mode: boolean`. When `true`, surface a visible banner.

---

## 2. Auth & session

### Token handling 🟢

Bearer JWT. `Authorization: Bearer <token>` on every authenticated request.

- `POST /api/v1/auth/login` → `{ access_token, token_type }`
- `POST /api/v1/auth/refresh` → new token (send the current, still-valid one)
- Tokens last **60 minutes**. Refresh proactively (~5 min before expiry); once expired there's nothing to refresh from and the user must log in again.
- Decoded payload is `{ sub: user_id, role: "CLINICIAN"|"PATIENT", exp }` — safe to read client-side for role-gating UI. Never trust it for authorization; the server re-checks everything.

### Errors

Standard shape is `{ "detail": "..." }`. Two exceptions:

- **`422`** (validation) returns `{"detail": [ {loc, msg, type} ]}` — an array.
- **`429`** (rate limit) returns `{"error": "Rate limit exceeded: ..."}` — note the key is `error`, not `detail`. Handle both.

Rate limits: 60/min globally, 20/min on login/register, and (planned) stricter on OTP endpoints. Back off on `429`.

---

## 3. Flow — Clinician onboards a patient 🟢

The only way a patient account comes into existence. There is **no patient self-signup.**

```
Clinician fills patient form
  → POST /api/v1/patients
  → backend creates User (no password, status=pending_activation)
     + PatientProfile + assignment to this clinician
     + emails a single-use invite link
  → 201 returned immediately
```

**`POST /api/v1/patients`** — body: `email`, `legal_name`, `date_of_birth`, `medical_record_number`, `biological_sex`, `age`, `emergency_contact?`

Returns the created profile plus:
```json
{ "id": "...", "user_id": "...", "legal_name": "...",
  "activation_status": "pending",
  "invite_email_status": "sent" | "failed" }
```

**UI requirements:**
- Patient creation **succeeds even if the email fails** (`invite_email_status: "failed"`). Don't treat that as a failed creation — show a non-blocking warning with a "resend invite" action.
- `409` if that email already has an account.
- Show `activation_status` in the patient list so clinicians can see who hasn't onboarded yet.

**`POST /api/v1/patients/{id}/invite/resend`** 🟢 — regenerates the token, invalidates the old one, re-sends. `409` if the account is already activated.

### Why no password is emailed

We deliberately never send a password. The invite link lets the patient set their own. Don't build a UI that displays or transmits a generated password.

---

## 4. Flow — Patient activates their account 🟢

The invite email contains a link to **your** frontend: `{FRONTEND_BASE_URL}/activate?token=<token>`

```
Patient clicks link
  → GET /api/v1/auth/activate/{token}      (validate before showing the form)
  → show "set your password" form
  → POST /api/v1/auth/activate             { token, password }
  → account activated; returns access_token (log them straight in)
```

**States to handle on the validate call:**

| Response | UI |
|---|---|
| `200 { email, expires_at }` | Show the set-password form (display the email read-only so they know which account) |
| `410` expired | "This invite expired. Ask your clinician to send a new one." |
| `409` already used | "Already activated — go to login." |
| `404` invalid | Generic "invalid link" |

Password rules: 8–128 chars (server-enforced, `422` on violation). Mirror client-side for UX.

**Login before activation** returns a generic `401`, same as a wrong password — you can't detect the unactivated state from login. That's intentional. Guide users to the invite email instead.

---

## 5. Flow — Patient views (and lightly edits) their record 🟢

Patient-facing screens are **read-only for anything medical.**

| Endpoint | Status | Notes |
|---|---|---|
| `GET /api/v1/patients/me` | 🟢 | Their profile |
| `PATCH /api/v1/patients/me` | 🟢 | Limited self-edit |
| `GET /api/v1/patients/{id}/conditions` | 🟢 | Read-only for patient |
| `GET /api/v1/patients/{id}/regimens` | 🟢 | Read-only for patient |

**`POST /api/v1/patients/me` is GONE** 🟢 — removed; patients no longer create their own profile. Calling it returns `404`/`405`.

### What a patient may edit

**Allowed now (🟢):** `legal_name`, `age`, `emergency_contact`
**Allowed, not built yet (🔴):** `email` — see the two-step flow below
**Clinician-only:** `date_of_birth`, `medical_record_number`, `biological_sex`, and everything clinical

Sending a clinician-only field to `PATCH /patients/me` returns **`422`** (the field is rejected outright, not silently dropped — so a "saved!" toast never fires on an edit that didn't happen). Just don't render those as editable.

### Email change is a two-step flow 🔴

Changing email changes both login identity *and* where consent OTPs are delivered, so it can't take effect immediately:

```
PATCH /api/v1/patients/me { email: "new@..." }
  → 202; verification link sent to the NEW address; login email unchanged for now
  → patient clicks link → POST /api/v1/auth/confirm-email-change { token }
  → email switches
```

UI: show "pending change to new@… — check that inbox" until confirmed, with a cancel option.

---

## 6. Flow — Clinician manages the regimen 🟢

Two ways in: structured prescription import, and manual per-drug edits. Both are live and tested now.

### Prescription import 🟢

**`POST /api/v1/patients/{id}/prescriptions`** — submit a structured prescription; backend resolves drug names to internal IDs and creates regimen entries.

```json
{
  "prescriber_name": "Dr. A. Rao",
  "issued_date": "2026-09-01",
  "allow_partial": false,
  "items": [
    { "drug_name": "Aspirin", "pubchem_cid": "CID000002244",
      "dosage": "75mg", "frequency": "once daily", "route": "oral",
      "start_date": "2026-09-01", "end_date": null,
      "instructions": "with food" }
  ]
}
```

`pubchem_cid` is optional — if omitted, the backend resolves from `drug_name`.

**Response — the important part:**
```json
{
  "created": [ { "id": "...", "pubchem_cid": "...", "drug_name": "Aspirin" } ],
  "unresolved": [ { "drug_name": "Xyzzycillin", "reason": "not_in_vocabulary" } ],
  "committed": true
}
```

> ⚠️ **`unresolved` is safety-critical.** The model only knows 645 drugs. Any drug it can't resolve is *excluded from every future interaction analysis* — which makes reports look safer than reality. You must show unresolved items as a **prominent warning**, not a quiet toast, both here and wherever that patient's reports are displayed.

With `allow_partial: false` (default), any unresolved item means **nothing is committed** (`committed: false`) — show the list and make the clinician decide. With `true`, resolvable items are created and the rest reported.

A sample prescription lives at `backend/samples/prescription_example.json` using real in-vocabulary drugs — use it for mocks.

### Manual regimen edits

| Endpoint | Status | Notes |
|---|---|---|
| `POST /api/v1/patients/{id}/regimens` | 🟢 | Add one drug (assignment-scoped). Now validates against the 645-drug vocabulary — `422` if it can't resolve. |
| `PATCH /api/v1/patients/{id}/regimens/{rid}` | 🟢 | **Discontinue** = set `end_date`. This is the normal "remove". |
| `DELETE /api/v1/patients/{id}/regimens/{rid}` | 🟢 | **Hard delete** — data-entry correction only |

**Make these two visually distinct.** "Discontinue" preserves medical history and is the right action ~always. "Delete" erases the record and should be a secondary, confirm-gated action labelled something like *"Delete — entered in error"*.

`GET .../regimens?active_only=true` filters to current meds (`end_date` null).

### Drug lookup / autocomplete 🟢

- `GET /api/v1/vocab/drugs?q=aspirin&limit=20&offset=0` → `[{cid, name}]`
- `GET /api/v1/vocab/drugs/{cid}`
- `GET /api/v1/vocab/adverse-effects` → all 50, `{cui, name, female_weighted}`

Use this to drive drug pickers so clinicians only ever select in-vocabulary drugs — the cheapest way to avoid the unresolved-drug problem entirely.

---

## 7. Flow — Interaction checks 🟢

Live today. Good for building the clinical UI now.

| Endpoint | Use |
|---|---|
| `POST /api/v1/predict/pairwise` | Two drugs → all 50 ADR scores, sorted |
| `POST /api/v1/predict/regimen` | N drugs → NxN matrix, toxicity index, per-pair flags |
| `POST /api/v1/predict/substitute` | High-risk pair → up to 3 safer alternatives |
| `POST /api/v1/explain/interaction` | LLM explanation + graph pathway for one interaction |

All accept optional `patient_id` (loads that patient's sex, RBAC-checked + audited) or `patient_sex` (pure what-if, no DB touch). Use `patient_sex` for hypothetical exploration so you don't write audit rows for non-clinical browsing.

**Rendering notes:**
- `interaction_matrix` is symmetric with a zero diagonal → heatmap.
- `is_high_risk` = score > 75.
- Only call `/substitute` for pairs already flagged high-risk; below the threshold it short-circuits and always returns `alternatives: []`.
- `/explain` needs `OPENROUTER_API_KEY` configured server-side; without it every call returns `502`. Handle that as "explanations unavailable," not a crash.
- `xai_pathway.data_available: false` means no known biological pathway — render an explicit empty state, not a blank canvas.

---

## 8. Flow — Reports 🟢

A report is a snapshot: full interaction analysis of a patient's **active** regimen (`end_date IS NULL` at generation time) — frozen. Later regimen changes don't alter an existing report. Requires at least two active, resolvable medications (`422` otherwise).

### Generate (async)

```
POST /api/v1/patients/{id}/reports
  → 202 { "id": "...", "status": "pending" }
poll GET /api/v1/reports/{id} until status != "pending"
```

Generation runs several LLM calls, so it's slow (seconds to a minute+). **Poll every 2–3s with backoff; time out around 2 min** and show a retry. Don't block the UI — let them navigate away and come back.

### Report payload

```json
{
  "id": "...", "patient_id": "...", "status": "complete",
  "created_at": "...", "generated_by": "...",

  "disclaimer": "Not to be taken without clinical supervision.",
  "model_status": { "degraded_mode": true, "verified": false,
                    "warning": "Model output is unverified..." },

  "regimen_snapshot": [ { "pubchem_cid": "...", "drug_name": "...", "dosage": "..." } ],
  "unresolved_drugs": [ { "drug_name": "...", "reason": "not_in_vocabulary" } ],

  "summary": { "drug_count": 5, "high_risk_pair_count": 2,
               "regimen_toxicity_index": 61.4 },
  "interaction_matrix": [[0.0, 61.4], [61.4, 0.0]],
  "pairwise": [ { "drug_a_cid": "...", "drug_b_cid": "...",
                  "top_risk_score": 61.4, "top_adverse_effect": "thrombocytopenia",
                  "is_high_risk": false, "female_weighted": true,
                  "adverse_effects": [ ... ] } ],
  "substitutions": [ { "for_drug_cid": "...", "alternatives": [ ... ] } ],
  "explanations": [ { "drug_a_cid": "...", "drug_b_cid": "...",
                      "clinical_mechanism": "...", "severity_classification": "Moderate",
                      "patient_summary": "...", "actionable_guidance": "...",
                      "xai_pathway": { "nodes": [], "edges": [], "data_available": false } } ],

  "file_available": true
}
```

**Mandatory rendering:** `disclaimer` and `model_status.warning` at the top of the report view and on the PDF preview — prominent, always visible, never behind a disclosure toggle.

`severity_classification` is one of `Contraindicated | Major | Moderate | Minor` — safe to colour-code.

`substitutions` and `explanations` only cover pairs where `is_high_risk` is `true` — a report with no high-risk pairs has both as `[]`, which is a good outcome, not missing data. If the backend's `OPENROUTER_API_KEY` isn't configured in a given environment, `explanations` will always be `[]` there (each pair's LLM call fails, is caught, and is skipped — the rest of the report is unaffected); don't treat an empty `explanations` array as a bug on its own.

### Other report endpoints

| Endpoint | Notes |
|---|---|
| `GET /api/v1/patients/{id}/reports` | List (paginated) — build a report history view |
| `GET /api/v1/reports/{id}/pdf` | PDF download |
| `GET /api/v1/reports/{id}/qr` | PNG QR image (§9, still planned) |
| `DELETE /api/v1/reports/{id}` | Soft-delete; revokes QR access too |

### Report files are stored on ephemeral disk — but this is handled for you

Report **metadata (the whole JSON body above) lives in the database (durable)**, but the **PDF lives on container disk, which is wiped on restart/redeploy.**

Unlike the originally-planned contract, `GET /api/v1/reports/{id}/pdf` now **self-heals**: if the file is missing on disk, the backend transparently re-renders it from the durable analysis (no GNN/LLM calls needed, so it's cheap) and serves it — it does **not** 404. You can just always point a download link/button at this endpoint.

`file_available` in the report/list payload is still worth showing (e.g. as a subtle "cached"/"will regenerate" hint or to decide whether to show a spinner), but you no longer need special-case "Regenerate PDF" UI or to treat `file_available: false` as a broken-link state — the same link works either way, just possibly a beat slower.

---

## 9. Flow — QR access 🔴

The QR encodes a URL to **your frontend**: `{FRONTEND_BASE_URL}/reports/{report_id}`

It carries **no credential**. Scanning it grants nothing by itself — the person still has to be logged in as the patient or an assigned clinician. A photographed QR is harmless.

**Your responsibility — deep link + auth round-trip:**

```
Scan → lands on /reports/{id}
  → not logged in?  save returnTo, redirect to /login
                    → after login, restore returnTo
  → GET /api/v1/reports/{id}
  → 200 → render;  404 → "Not found, or you don't have access"
```

Getting the `returnTo` round-trip right is the whole UX of this feature — a scan that dumps the user on a generic dashboard after login is a broken experience.

Display: fetch `GET /api/v1/reports/{id}/qr` as an image (`<img src>` with the auth header, or fetch → blob URL). Offer print/download — the realistic use is a printed sheet a patient carries.

> Backend needs `FRONTEND_BASE_URL` configured to build correct QR links. Tell us your deployed origin.

---

## 10. Flow — Transfer to another clinician 🔴

Moves/shares a patient with another clinician, gated on the **patient's** consent via emailed OTP.

```
Clinician A → POST /api/v1/patients/{id}/transfers { to_clinician_email }
              status: pending_patient_consent; OTP emailed to patient
Patient    → sees pending request
           → POST /api/v1/transfers/{tid}/consent { otp: "123456" }
              status: approved; clinician B assigned
```

Per the agreed design: **B does not have to accept**, and **A does not lose access immediately** (grace period). So post-transfer the patient has two assigned clinicians. Reflect that in the UI.

| Endpoint | Actor |
|---|---|
| `POST /api/v1/patients/{id}/transfers` | Assigned clinician |
| `GET /api/v1/transfers` | Either — lists mine, role-filtered |
| `GET /api/v1/transfers/{tid}` | Participants |
| `POST /api/v1/transfers/{tid}/consent` | Patient (OTP) |
| `POST /api/v1/transfers/{tid}/decline` | Patient |
| `POST /api/v1/transfers/{tid}/cancel` | Initiating clinician |
| `POST /api/v1/transfers/{tid}/resend-otp` | Patient |

**Transfer object:**
```json
{ "id": "...", "patient_id": "...",
  "from_clinician": { "id": "...", "email": "..." },
  "to_clinician":   { "id": "...", "email": "..." },
  "status": "pending_patient_consent",
  "otp_expires_at": "...", "attempts_remaining": 5,
  "created_at": "...", "consented_at": null }
```

**OTP UI rules** (the server enforces all of these — mirror them):
- 6 digits, **10-minute expiry** — show a live countdown.
- **5 attempts**, then the request locks (`status: "locked"`). Show `attempts_remaining` after each failure.
- Wrong OTP → `400`. Expired → `410`. Locked → `423`. Distinct messaging for each.
- Resend is rate-limited harder than normal endpoints — disable the button with a cooldown timer rather than letting them hit `429`.
- Only **one pending transfer per patient**; initiating a second returns `409`.

**Patient visibility is essential** — a pending consent request must be surfaceable (banner/notification), not buried. It's a request to give another person access to their medical record.

### Who has access 🟢

**`GET /api/v1/patients/{id}/access`** → current assignments (this endpoint is live now; the *transfer* flow that produces multiple entries is not):
```json
[ { "clinician": {"id":"...","email":"..."}, "is_primary": true,
    "assigned_at": "...", "expires_at": null } ]
```
Powers a "who can see my record" view for patients and a care-team view for clinicians.

---

## 11. Clinician patient list 🟢

**`GET /api/v1/patients?limit=&offset=`** — the assigned-patient list. Only became possible with the assignment model (previously there was no way to list patients at all).

```json
[ { "id": "...", "user_id": "...", "legal_name": "Jane Doe", "age": 36,
    "biological_sex": "FEMALE", "is_primary": true,
    "assigned_at": "2026-09-06T...", "active_regimen_count": 4 } ]
```

`activation_status` is live (`"pending"` until the patient sets a password, then `"active"`). `last_report_at` arrives with the reports feature — absent today rather than stubbed.

**Search caveat:** `legal_name` and `medical_record_number` are encrypted at rest and **cannot be filtered server-side**. Client-side filtering of the fetched page is fine; a global "search all patients by name" is not possible without a backend change (blind-index). Design around it.

---

## 12. Local development

**Email — MailHog.** All outbound mail (invites, OTPs, email-change confirmations) goes to MailHog in dev. Web UI at **http://localhost:8025** — grab invite links and OTP codes from there. No real inboxes needed; this makes flows §3, §4, §9, §10 fully testable locally.

**Backend:** `http://localhost:8000`, docs at `/docs` (Swagger — "Authorize" takes a raw bearer token from `/auth/login`), health at `/health` (also reports `gnn_degraded_mode`).

**CORS:** your origin must be in the backend's `CORS_ORIGINS`. Default allows `http://localhost:3000` — tell us if you're on a different port.

---

## 13. Suggested screen inventory

**Clinician:** login · patient list (§11) · create patient (§3) · patient detail (profile / conditions / regimen / reports tabs) · prescription import (§6) · interaction workbench (§7) · report view (§8) · initiate transfer (§10) · care team (§10)

**Patient:** activate account (§4) · my profile (view + limited edit, §5) · my medications (read-only) · my conditions (read-only) · my reports + QR (§8, §9) · pending consent requests (§10) · who has access (§10)

**Shared:** login · deep-link handler for `/reports/{id}` (§9) · degraded-model banner · 429 backoff · session-expiry handling

---

## 14. What to build now vs. mock

**Buildable against live endpoints today:** login/refresh/session, drug autocomplete, the entire interaction workbench (pairwise / regimen matrix / substitution / explanation), health-and-degraded-banner, **the clinician patient roster, patient detail (profile/conditions/regimens), patient self-edit, the who-has-access view, prescription import, manual regimen add/discontinue/delete, and reports (generate/list/get/pdf/delete)**.

**Mock against this contract:** QR, transfers.

> **Assignment is now enforced.** A clinician only sees patients they created (or were assigned). During development, create your test patients with the same clinician account you're logged in as, or you'll get `404`s that look like bugs.

Starting with the interaction workbench gets you real data immediately and is the most complex UI surface — the rest is comparatively conventional CRUD once the contract lands.

---

## 15. Open items we'll confirm

1. `FRONTEND_BASE_URL` — needed to generate QR links and invite/OTP email links.
2. Invite-token lifetime (proposing 72h) and OTP lifetime (10 min).
3. Transfer grace period before the original clinician's access lapses (proposing 7 days, or explicit revoke).
4. Whether clinician self-signup (`POST /auth/register` with `role: CLINICIAN`) stays open or moves behind admin invite.

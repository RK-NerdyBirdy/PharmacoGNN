# PharmacoGNN API Reference

For frontend integration against the FastAPI backend in `backend/`. Covers every route that exists today. See the bottom of this doc for what's *not* built yet.

- **Base URL (local dev):** `http://localhost:8000`
- **Base URL (Docker Compose):** `http://localhost:8000` (same — `BACKEND_PORT` in `.env`, default `8000`)
- **All business endpoints are prefixed** `/api/v1`
- **Content type:** `application/json` for every request body and response
- **CORS:** allow-listed origins only (`CORS_ORIGINS` env var, comma-separated; defaults to `http://localhost:3000`), `allow_credentials: true`. If your frontend runs on a different port, add it there.
- **Rate limiting:** per-IP, in-memory. Default **60 requests/minute** across the board; `/auth/register` and `/auth/login` are limited separately at **20/minute** (brute-force protection). Exceeding a limit returns `429 Too Many Requests` with a body like `{"error": "Rate limit exceeded: 20 per 1 minute"}` (note: `error`, not `detail`, unlike every other error response — and there's no `Retry-After` header, so don't rely on one). Build a retry/backoff path for `429` the same way you would for `401`.

---

## 1. Authentication

The API uses JWT bearer tokens. There is no session/cookie auth.

### Getting a token

1. `POST /api/v1/auth/register` once per user.
2. `POST /api/v1/auth/login` to get an `access_token`.
3. Send it on every subsequent request: `Authorization: Bearer <access_token>`.

**Important:** the login endpoint takes a **JSON body** (`{"email", "password"}`), *not* an OAuth2 form-urlencoded request, even though the OpenAPI schema references `OAuth2PasswordBearer` (that's only used internally to extract the token from the `Authorization` header on protected routes — it has no bearing on how you call `/login`).

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default **60 minutes**). Call `POST /api/v1/auth/refresh` (bearer-authenticated, no body) proactively before that to get a new token without re-entering credentials — see below. Once a token has actually expired, `refresh` also returns `401` like everything else, and the user must log in again. The decoded JWT payload shape is `{"sub": "<user_id>", "role": "CLINICIAN"|"PATIENT", "exp": <unix_timestamp>}`, in case you need to read the role client-side without an extra call (e.g. for role-gated UI).

### Roles and assignment (RBAC)

Two roles exist: `CLINICIAN` and `PATIENT`. **Holding the `CLINICIAN` role does not by itself grant access to any patient** — access comes from an active *assignment* between that specific clinician and that specific patient.

- A `PATIENT` reaches only their own record.
- A `CLINICIAN` reaches only patients they hold an active assignment for. The clinician who creates a patient is automatically assigned as their primary.
- A patient may have **more than one** assigned clinician at once (a transfer grants the receiving clinician access without immediately revoking the sender's).

**Unentitled access returns `404`, not `403`** — a `403` would confirm that a patient with that id exists, which is itself a disclosure. You cannot distinguish "no such patient" from "not yours", by design.

The one place you'll see `403` on a patient route is a **role/method** violation rather than a visibility one: e.g. a patient calling a clinician-only method on their own record. The record isn't hidden from them (they can `GET` it) — only the operation is.

This applies to every endpoint accepting a `patient_id`, including `predict/*` and `explain/*`. Passing a `patient_id` triggers an audit-log write — it's a real PHI access, not a free-form parameter. For hypothetical/what-if calculations use `patient_sex` instead and omit `patient_id`; that path never touches the database.

---

## 2. Common request/response shapes

### The demographic pattern (`patient_id` / `patient_sex`)

`predict/pairwise`, `predict/regimen`, `predict/substitute`, and `explain/interaction` all accept the same two optional fields:

| Field | Type | Behavior |
|---|---|---|
| `patient_id` | `UUID \| null` | Loads `biological_sex` from that patient's stored profile. RBAC-checked (see above) and writes an `AuditLog` row. |
| `patient_sex` | `"FEMALE" \| "MALE" \| "INTERSEX" \| null` | Explicit override — **takes precedence over `patient_id`** if both are given. Pure computation, never touches the DB. |

If `patient_sex` resolves to `"FEMALE"` (from either source), the model's curated female-biased adverse-drug-reaction scores get multiplied by a calibrated weight and clamped at 99.9. If neither field is given, no demographic adjustment is applied at all.

### `degraded_mode`

Every prediction/substitution/explanation response includes a `degraded_mode: boolean` field. This reflects the state of the *entire* model at the time of the request (not per-request) — see `GET /health`. `true` means the 3-layer graph encoder either didn't run at all (no graph edge data available) or ran but its output hasn't been independently confirmed numerically correct yet. **Treat scores as directional, not absolute, while this is `true`.** Ask the backend team before this flips to `false` in a way you can rely on for clinical framing.

### Error shape

All handled errors (4xx/5xx raised deliberately by the API) return FastAPI's standard shape:

```json
{ "detail": "human-readable message" }
```

Except **422 Unprocessable Entity** (Pydantic request-body validation failures), which returns FastAPI's default validation error array:

```json
{
  "detail": [
    { "loc": ["body", "drug_a_cid"], "msg": "Field required", "type": "missing" }
  ]
}
```

A `401` on any authenticated route also carries a `WWW-Authenticate: Bearer` response header.

---

## 3. Endpoints

### `GET /health`

No auth required. Poll this to know if the model finished loading and whether it's in degraded mode.

**Response `200`:**
```json
{
  "status": "ok",
  "gnn_ready": true,
  "gnn_degraded_mode": true
}
```

---

### `POST /api/v1/auth/register`

**Clinician self-signup only.** Sending `"role": "PATIENT"` returns **`403`** — patient accounts are created by a clinician via `POST /api/v1/patients`, which also creates their profile, the assignment granting access, and the invite that lets them set a password. A self-registered patient would have no profile and no clinician, could see nothing, and would be a way to mint patient logins outside onboarding.

Creates a login identity only — no `PatientProfile`.

Auth: none.

**Request body:**
```json
{
  "email": "clinician@example.com",
  "password": "at-least-8-chars",
  "role": "CLINICIAN"
}
```
| Field | Type | Notes |
|---|---|---|
| `email` | string (email format) | Must be unique. |
| `password` | string | 8-128 chars. |
| `role` | `"CLINICIAN" \| "PATIENT"` | |

**Response `201`:**
```json
{
  "id": "b5f8434c-851a-4521-af69-8d1d474735fe",
  "email": "clinician@example.com",
  "role": "CLINICIAN",
  "is_active": true
}
```

**Errors:** `409` if the email is already registered. `422` on validation failure.

---

### `POST /api/v1/auth/login`

Auth: none.

**Request body:**
```json
{ "email": "clinician@example.com", "password": "at-least-8-chars" }
```

**Response `200`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**Errors:** `401` "Incorrect email or password" — deliberately identical whether the email doesn't exist, the password is wrong, the account is deactivated, **or the account exists but hasn't been activated yet** (an invited patient who hasn't set a password). Login can't be used to discover which addresses have pending invites, so don't build UI copy that assumes which case it was.

---

### `GET /api/v1/auth/activate/{token}`

Auth: none. Validate an invite **before** rendering the set-password form.

**Response `200`:** `{ "email": "patient@example.com", "expires_at": "..." }` — show the email read-only so the patient knows which account they're activating.

**Errors:** `410` expired · `409` already used · `404` unknown token. These are distinct on purpose so the page can say something useful; tokens are 256-bit random values, so confirming whether one is real isn't a practical attack surface.

---

### `POST /api/v1/auth/activate`

Auth: none. Redeem the invite: set the first password and log in.

**Request body:** `{ "token": "...", "password": "at-least-8-chars" }`

**Response `200`:** same as `/login` — an `access_token`, so the patient lands logged in rather than being bounced to a login form.

**Errors:** `410` / `409` / `404` as above; `422` if the password fails length rules. Tokens are **single-use** — a second attempt with the same token is `409`.

---

### `POST /api/v1/auth/refresh`

Auth: required (any role). No request body.

Re-issues a fresh access token from the current one. This is the simple "sliding session" pattern — it re-signs a new token as long as the one you sent is still valid; it is **not** a separate long-lived refresh-token type with its own rotation/revocation. Two calls within the same second can return byte-identical tokens (same claims, same `exp` to the second) — that's expected, not a bug.

**Response `200`:** same shape as `/login`.

**Errors:** `401` if the current token is already expired or invalid — at that point there is nothing to refresh from; log in again.

---

## Patient management (`/api/v1/patients`)

All endpoints below are auth-required and assignment-scoped (see "Roles and assignment" above).

**Authorization model:**
- A `PATIENT` may **read** their own profile, conditions and regimens, and may edit a **narrow set of their own demographics** (see `PATCH /me`). They can never write clinical data — no self-diagnosing a condition, no self-prescribing a regimen (`403` on the attempt).
- A `CLINICIAN` may read/write the profile, conditions and regimens of patients **they are actively assigned to**, and nobody else's (`404` for everyone else's).
- Every read and write in this section writes an `AuditLog` row.

### `GET /api/v1/patients`

`CLINICIAN` only. The caller's assigned-patient roster, paginated (`limit` 1-200 default 50, `offset` default 0).

**Response `200`:**
```json
[
  { "id": "...", "user_id": "...", "legal_name": "Jane Doe", "age": 36,
    "biological_sex": "FEMALE", "is_primary": true,
    "assigned_at": "2026-09-06T...", "active_regimen_count": 4,
    "activation_status": "active" }
]
```

`activation_status` is `"pending"` until the patient redeems their invite and sets a password, then `"active"` — surface it so clinicians can see who hasn't onboarded yet.

> **No name/MRN search parameter, and there can't be one** without a schema change: `legal_name` and `medical_record_number` are encrypted at rest with a non-deterministic cipher, so the database cannot filter or match on them. Filter client-side over a fetched page, or ask for a blind-index column to be added.

### `GET /api/v1/patients/me`

`PATIENT` role only. `404` if no profile has been created for them yet.

**Response `200`:**
```json
{
  "id": "aba92e50-49d2-4898-b304-fc25f94af825",
  "user_id": "96900002-5166-49a3-a36c-0ceebb530255",
  "legal_name": "Jane Doe",
  "date_of_birth": "1990-05-14",
  "medical_record_number": "MRN-12345",
  "emergency_contact": "John Doe, 555-1234",
  "biological_sex": "FEMALE",
  "age": 36
}
```
`legal_name`, `date_of_birth`, `medical_record_number`, `emergency_contact` are encrypted at rest (AES-256-GCM) — you send/receive them as plain strings, encryption is transparent to the API.

### `PATCH /api/v1/patients/me`

`PATIENT` role only. The patient's own limited self-edit. Accepts **only** `legal_name`, `age`, `emergency_contact`.

Anything else — `date_of_birth`, `medical_record_number`, `biological_sex` — is rejected with **`422`**, not silently ignored. (`biological_sex` in particular feeds the model's risk stratification, so a patient editing it would change their own risk scores.)

> Email changes are **not** handled here. Email lives on the `User` record and changing it also changes where consent codes are delivered, so it needs a verify-the-new-address flow. Not yet implemented.

### `POST /api/v1/patients`

`CLINICIAN` only — onboards a patient end-to-end: creates the login account, the profile, the assignment, and emails an invite. **The creating clinician is automatically assigned as primary**; without that the patient would be created and immediately invisible to everyone.

**Request body:** the profile fields shown above, plus `email`. There is no `user_id` — this call creates the account too.

```json
{ "email": "patient@example.com", "legal_name": "Jane Doe",
  "date_of_birth": "1990-05-14", "medical_record_number": "MRN-12345",
  "biological_sex": "FEMALE", "age": 36,
  "emergency_contact": "John Doe, 555-1234" }
```

**Response `201`:** the profile, plus:
```json
{ "activation_status": "pending", "invite_email_status": "sent" }
```

The account is created **with no password**. The emailed invite link is the only thing that can set the first one — nothing password-shaped is ever put in an inbox.

> **`invite_email_status: "failed"` does not mean the patient wasn't created.** The database work commits before the email is attempted, so a mail outage leaves a fully usable patient record. Show a non-blocking warning and offer resend — don't treat it as a failed operation.

**Errors:** `409` if that email already has an account.

### `POST /api/v1/patients/{patient_id}/invite/resend`

`CLINICIAN` only (assigned). Issues a fresh invite and **invalidates the previous one** — the old link immediately returns `410`.

**Response `200`:** `{ "invite_email_status": "sent" | "failed" }`

**Errors:** `409` if the account is already activated (nothing to invite). `404` if not assigned.

### `GET /api/v1/patients/{patient_id}`

Read one profile by its own id (not the user id). The patient themselves, or an assigned clinician. `404` otherwise.

### `PATCH /api/v1/patients/{patient_id}`

`CLINICIAN` only (assigned). Partial update; accepts `legal_name`, `date_of_birth`, `medical_record_number`, `emergency_contact`, `biological_sex`, `age`. Unknown fields → `422`.

A `PATIENT` calling this gets `403` even on their own record — they have `PATCH /me` instead.

### `GET /api/v1/patients/{patient_id}/access`

Who currently holds access to this record. Readable by the patient themselves and by any assigned clinician.

**Response `200`:**
```json
[
  { "clinician_id": "...", "clinician_email": "doc@example.com",
    "is_primary": true, "assigned_at": "2026-09-06T..." }
]
```
Expect more than one entry after a transfer — the sending clinician retains access during the handover window.

### `POST /api/v1/patients/{patient_id}/conditions`

`CLINICIAN` only.

**Request body:**
```json
{ "condition_name": "Hypertension", "icd10_code": "I10", "diagnosed_date": "2020-01-01" }
```
`icd10_code` and `diagnosed_date` are optional. New conditions default to `is_active: true`.

**Response `201`:**
```json
{
  "id": "ce84d5bb-ab61-4d22-9dc8-275b88579647",
  "patient_id": "aba92e50-49d2-4898-b304-fc25f94af825",
  "condition_name": "Hypertension",
  "icd10_code": "I10",
  "diagnosed_date": "2020-01-01",
  "is_active": true
}
```

### `GET /api/v1/patients/{patient_id}/conditions`

Query params: `active_only` (bool, default `false`), `limit` (1-200, default 50), `offset` (default 0). `CLINICIAN`: any patient. `PATIENT`: only their own. Returns a plain JSON array (no envelope/`total` count).

### `PATCH /api/v1/patients/{patient_id}/conditions/{condition_id}`

`CLINICIAN` only. Typically used to set `{"is_active": false}` when a condition resolves. Also accepts `diagnosed_date`, `icd10_code`.

### `POST /api/v1/patients/{patient_id}/regimens`

`CLINICIAN` only. `prescriber_id` is set automatically to the calling clinician — don't send it.

**⚠️ Breaking change:** `pubchem_cid` is now a **string** in the model's native format (`"CID" + 9 zero-padded digits`, e.g. `"CID000000085"`), not a bare integer. It's also now optional: if omitted, the drug is resolved from `drug_name` instead. Either way, the drug must be one of the model's 645 in-vocabulary drugs or the request is rejected — see the note below.

**Request body:**
```json
{ "pubchem_cid": "CID000000085", "drug_name": "Test Drug", "dosage": "10mg BID", "start_date": "2024-01-01" }
```
`drug_name` is always required by the schema, but if `pubchem_cid` is present it's authoritative — the stored `drug_name` on the response is the model's canonical name for that CID, not necessarily the text you sent. Omit `pubchem_cid` to resolve purely by name (exact, case-insensitive match against the vocabulary; no fuzzy matching, by design — see below).

**Response `201`:** includes `id`, `patient_id`, `prescriber_id`, `end_date: null` (active), `external_prescriber_name` (null for entries added directly through this endpoint), `import_batch_id: null`.

**Errors:** `422` if the drug can't be resolved — response `detail` names the reason (`not_in_vocabulary`, `cid_not_in_vocabulary`, `ambiguous_name`, or `missing_identifier`). This is deliberately strict: a drug the model doesn't know can't be scored, so it's rejected outright rather than silently stored and quietly dropped from every future interaction report. No fuzzy matching either — "Asprin" does not silently become "Aspirin"; a wrong guess here writes the wrong drug into a clinical record, so an honest 422 is preferred over a plausible-looking guess.

### `GET /api/v1/patients/{patient_id}/regimens`

Query params: `active_only` (bool — filters to `end_date IS NULL`), `limit`, `offset` as above.

### `PATCH /api/v1/patients/{patient_id}/regimens/{regimen_id}`

`CLINICIAN` only. The way to discontinue a medication is `{"end_date": "2024-06-01"}`. Also accepts `dosage`. This **preserves** the row — use it when a medication was genuinely taken and is now stopped.

### `DELETE /api/v1/patients/{patient_id}/regimens/{regimen_id}`

🟢 **New.** `CLINICIAN` only. Returns `204` on success, `404` if the regimen doesn't exist or belongs to a different patient.

Hard delete — the row is actually erased, not just end-dated. This is for correcting a data-entry mistake (a drug that should never have been added), not for stopping a medication someone actually took — use `PATCH .../end_date` for that instead. Deliberately a different HTTP verb from discontinue so a client can't reach for it out of habit.

### `POST /api/v1/patients/{patient_id}/prescriptions`

🟢 **New.** `CLINICIAN` only. Creates multiple regimen rows from one structured prescription in a single call — this is the "dummy prescription" import flow.

**Request body:**
```json
{
  "prescriber_name": "Dr. Elena Ruiz, MD (External)",
  "issued_date": "2026-08-15",
  "allow_partial": false,
  "items": [
    { "drug_name": "Aspirin", "pubchem_cid": "CID000002244", "dosage": "81mg", "frequency": "once daily", "route": "oral", "start_date": "2026-08-15", "end_date": null, "instructions": "Take with food" },
    { "drug_name": "Metformin", "dosage": "500mg", "frequency": "twice daily", "route": "oral", "start_date": "2026-08-15" }
  ]
}
```
| Field | Type | Notes |
|---|---|---|
| `prescriber_name` | string \| null | Free text — who actually wrote it, if not the calling clinician (e.g. an outside doctor's dummy prescription being transcribed) |
| `issued_date` | date \| null | |
| `allow_partial` | bool, default `false` | See below |
| `items` | array, 1-50 | Each item has the same shape as `POST .../regimens`, plus `frequency`, `route`, `end_date`, `instructions` |

Every item is resolved the same way as a single manual add. **With `allow_partial: false`** (the default), if *any* item fails to resolve, **nothing is committed** — this avoids leaving a regimen that looks complete but is silently missing a drug the model can't score. **With `allow_partial: true`**, resolvable items are committed and unresolved ones are reported back, uncommitted.

**Response `201`:**
```json
{
  "created": [ /* array of the regimen objects actually written, same shape as GET .../regimens */ ],
  "unresolved": [
    { "drug_name": "Amoxicillin", "pubchem_cid": null, "reason": "not_in_vocabulary" }
  ],
  "committed": true
}
```
`committed` is `false` only when nothing was written at all (i.e. `allow_partial: false` and at least one item was unresolved). All rows created from one call share the same `import_batch_id`, and carry `external_prescriber_name` set from `prescriber_name` — use both to group/attribute an imported prescription later. A sample request body with a mix of real and deliberately-unresolvable drugs lives at `backend/samples/prescription_example.json`.

---

### `POST /api/v1/predict/pairwise`

Full 50-adverse-effect risk profile for one drug pair. Auth: required (any role).

**Request body:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_b_cid": "CID000000119",
  "patient_id": null,
  "patient_sex": "FEMALE"
}
```
| Field | Type | Required |
|---|---|---|
| `drug_a_cid` | string | yes — PubChem CID as it appears in `drug2idx.json`, e.g. `"CID000000085"` (zero-padded, `"CID" + 9 digits`) |
| `drug_b_cid` | string | yes |
| `patient_id` | UUID \| null | no |
| `patient_sex` | `"FEMALE"\|"MALE"\|"INTERSEX"` \| null | no |

**Response `200`:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_a_name": "1-Propanaminium, 3-Carboxy-2-Hydroxy-N,N,N-Trimethyl-, Inner Salt",
  "drug_b_cid": "CID000000119",
  "drug_b_name": "Gamma-Aminobutyric Acid",
  "female_adjustment_applied": true,
  "top_risk_score": 58.49,
  "top_adverse_effect": "thrombocytopenia",
  "adverse_effects": [
    {
      "cui": "C0040034",
      "name": "thrombocytopenia",
      "female_weighted": true,
      "risk_score": 58.49
    }
  ],
  "degraded_mode": true
}
```
`adverse_effects` always has **all 50** relations, sorted descending by `risk_score` (0-100 scale). `female_weighted` marks which of the 50 are in the curated female-bias set (35 of them) — it's per-ADR, independent of whether the multiplier was actually applied to *this* request (that's `female_adjustment_applied`, which also factors in whether the *top* ADR specifically was boosted).

**Errors:** `404` "Unknown drug CID: {cid}" if either CID isn't in `drug2idx.json`. `401`/`403` per the RBAC rules above if `patient_id` is used incorrectly.

---

### `POST /api/v1/predict/regimen`

Full pairwise interaction matrix for a cart of N≥2 drugs, vectorized. Auth: required.

**Request body:**
```json
{
  "drug_cids": ["CID000000085", "CID000000119", "CID000000143"],
  "patient_id": null,
  "patient_sex": null
}
```
`drug_cids` needs at least 2 entries.

**Response `200`:**
```json
{
  "drug_cids": ["CID000000085", "CID000000119", "CID000000143"],
  "drug_names": ["1-Propanaminium...", "Gamma-Aminobutyric Acid", "Unknown Drug (143)"],
  "regimen_toxicity_index": 99.9,
  "interaction_matrix": [
    [0.0, 99.9, 99.9],
    [99.9, 0.0, 99.9],
    [99.9, 99.9, 0.0]
  ],
  "pairwise_flags": [
    {
      "drug_a_cid": "CID000000085",
      "drug_b_cid": "CID000000119",
      "top_risk_score": 99.9,
      "top_adverse_effect": "thrombocytopenia",
      "female_weighted": true,
      "is_high_risk": true
    }
  ],
  "drug_disease_flags": [],
  "degraded_mode": true
}
```
- `interaction_matrix` is `drug_cids.length × drug_cids.length`, symmetric, diagonal is always `0.0` (self-pairs aren't scored). `interaction_matrix[i][j]` is the *top* (worst) ADR risk score for that pair specifically — use `pairwise_flags` to know which ADR that was.
- `regimen_toxicity_index` is the mean of every pair's top risk score (a single 0-100 summary number for the whole cart).
- `pairwise_flags` has one entry per unique pair (`N*(N-1)/2` entries), `is_high_risk` is `top_risk_score > 75.0`.
- `drug_disease_flags` **is currently always `[]`**. The cross-referencing logic itself is real and wired up (it queries the patient's active conditions and checks them against a reference file), but no reference file ships with this repo — populating one requires real, clinically-reviewed contraindication data, which this backend will not fabricate. It'll start returning entries the moment `backend/weights/drug_disease_contraindications.json` exists in the format documented in `app/services/drug_disease.py`. Don't build UI that assumes it's non-empty until you've confirmed that file exists.

**Errors:** `404` "Unknown drug CID: {cid}" for the first unrecognized CID. `422` if fewer than 2 CIDs given.

---

### `POST /api/v1/predict/substitute`

For a high-risk pair, finds up to 3 alternatives to `drug_b_cid` that reduce risk against `drug_a_cid`. Auth: required.

**Request body:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_b_cid": "CID000000119",
  "patient_id": null,
  "patient_sex": "FEMALE"
}
```
`drug_a_cid` is the drug held fixed; `drug_b_cid` is the one alternatives are searched for.

**Response `200`:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_a_name": "1-Propanaminium...",
  "drug_b_cid": "CID000000119",
  "drug_b_name": "Gamma-Aminobutyric Acid",
  "original_top_risk_score": 99.9,
  "original_top_adverse_effect": "thrombocytopenia",
  "substitution_recommended": true,
  "alternatives": [
    {
      "cid": "CID000002083",
      "name": "Salbutamol",
      "similarity_to_original": 0.87,
      "new_top_risk_score": 42.1,
      "new_top_adverse_effect": "nausea",
      "risk_reduction": 57.8
    }
  ],
  "degraded_mode": true
}
```
- `substitution_recommended` is `original_top_risk_score > 75.0`. **If `false`, the backend doesn't even run the substitution search — `alternatives` will always be `[]` in that case.** Don't call this endpoint speculatively for every pair in a cart; check `is_high_risk` from `/predict/regimen` first and only call `/substitute` for flagged pairs.
- `alternatives` is sorted by `risk_reduction` descending, capped at 3, and can be `[]` even when `substitution_recommended` is `true` if no candidate in the search pool actually reduces risk (this genuinely happens in degraded mode — see the note in that section above).
- `similarity_to_original` is cosine similarity (`-1..1`) between the candidate and the original `drug_b` in embedding space — a rough "pharmacological closeness" signal, not a safety guarantee by itself.
- Known placeholder/unidentified compounds (`cid_to_name.json` entries literally named `"Unknown Drug (N)"`) are excluded from `alternatives` automatically.

**Errors:** same CID/RBAC errors as above.

---

### `POST /api/v1/explain/interaction`

LLM-generated structured explanation for one specific adverse effect of a drug pair, grounded in the real interaction graph where possible. Auth: required. **Requires `OPENROUTER_API_KEY` to be configured on the backend** — if it isn't, every call to this endpoint returns `502`.

**Request body:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_b_cid": "CID000000119",
  "adverse_effect_cui": "C0040034",
  "patient_id": null,
  "patient_sex": "FEMALE"
}
```
| Field | Type | Notes |
|---|---|---|
| `drug_a_cid` / `drug_b_cid` | string | required |
| `adverse_effect_cui` | string \| null | Which of the 50 ADR relations to explain (e.g. `"C0040034"` = thrombocytopenia — see `relation_meta.json` keys). If omitted, defaults to whichever ADR currently scores highest for this pair. |
| `patient_id` / `patient_sex` | as above | affects which risk score is reported and whether the female-bias note applies |

**Response `200`:**
```json
{
  "drug_a_cid": "CID000000085",
  "drug_a_name": "1-Propanaminium...",
  "drug_b_cid": "CID000000119",
  "drug_b_name": "Gamma-Aminobutyric Acid",
  "adverse_effect": "thrombocytopenia",
  "risk_score": 58.49,
  "female_adjustment_applied": true,
  "degraded_mode": true,
  "explanation": {
    "clinical_mechanism": "Both compounds are predicted to interact with CYP2C9, a major drug-metabolizing enzyme...",
    "severity_classification": "Moderate",
    "patient_summary": "These two medicines might affect a protein in your liver that helps break down drugs...",
    "actionable_guidance": "Consider monitoring INR/platelet counts if either drug is added to an existing regimen involving CYP2C9 substrates...",
    "xai_pathway": {
      "nodes": [
        { "id": "drug:CID000000085", "label": "1-Propanaminium...", "type": "drug" },
        { "id": "protein:1559", "label": "CYP2C9", "type": "protein" },
        { "id": "drug:CID000000119", "label": "Gamma-Aminobutyric Acid", "type": "drug" }
      ],
      "edges": [
        { "source": "drug:CID000000085", "target": "protein:1559", "label": "targets" },
        { "source": "drug:CID000000119", "target": "protein:1559", "label": "targets" }
      ],
      "data_available": true
    }
  }
}
```

- `severity_classification` is one of exactly `"Contraindicated" | "Major" | "Moderate" | "Minor"`.
- `xai_pathway` is built directly from the real training graph (a shared protein target, or two proteins linked by one interaction hop) — it is **not** LLM-generated, even though it's returned inside the LLM's `explanation` object; the backend overwrites whatever the model produced for this field with a verified graph lookup. **When `data_available: false`, `nodes` and `edges` are always `[]`** — that's a true "no known connection in the graph," not a loading state or an error. Design the pathway visualization (Cytoscape.js/React Flow) to render an explicit "no graph pathway found" state rather than an empty canvas in that case.
- Node `id`s are namespaced (`"drug:<cid>"`, `"protein:<id>"`) so a drug and protein can never collide on raw id — use these directly as your graph library's node keys.

**Errors:** `404` "Unknown adverse_effect_cui" if that CUI isn't one of the 50 relations. `502` with a descriptive `detail` if `OPENROUTER_API_KEY` is unset, the OpenRouter call fails, or the model's response didn't parse into the required schema after one retry.

---

## Vocabulary / search (`/api/v1/vocab`)

For autocomplete/search UI. Auth required (any role), but not RBAC-scoped — this is non-PHI reference data, not a specific patient's information.

### `GET /api/v1/vocab/drugs`

Query params: `q` (string, case-insensitive substring match against drug name; omit or leave empty to list all 645), `limit` (1-100, default 20), `offset` (default 0).

**Response `200`:**
```json
[
  { "cid": "CID000000119", "name": "Gamma-Aminobutyric Acid" },
  { "cid": "CID000000564", "name": "6-Aminohexanoic Acid" }
]
```

### `GET /api/v1/vocab/drugs/{cid}`

**Response `200`:** `{ "cid": "CID000000085", "name": "1-Propanaminium..." }`. **Errors:** `404` "Unknown drug CID" if not in `drug2idx.json`.

### `GET /api/v1/vocab/adverse-effects`

No query params — returns all 50 ADR relations in one response (small enough that pagination isn't needed).

**Response `200`:**
```json
[
  { "cui": "C0040034", "name": "thrombocytopenia", "female_weighted": true }
]
```

### `GET /api/v1/vocab/adverse-effects/{cui}`

**Response `200`:** single entry, same shape as above. **Errors:** `404` "Unknown adverse_effect_cui".

---

## 4. Enums reference

| Enum | Values |
|---|---|
| `UserRole` | `CLINICIAN`, `PATIENT` |
| `BiologicalSex` | `FEMALE`, `MALE`, `INTERSEX` |
| `AuditActionType` (internal, not user-facing) | `VIEW`, `CREATE`, `UPDATE`, `DELETE`, `EXPORT`, `LOGIN` |
| `SeverityClassification` (explain endpoint only) | `Contraindicated`, `Major`, `Moderate`, `Minor` |

---

## 5. Quick-start (curl)

```bash
# Register + log in
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"doc@example.com","password":"supersecret1","role":"CLINICIAN"}'

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"doc@example.com","password":"supersecret1"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Pairwise prediction
curl -s -X POST http://localhost:8000/api/v1/predict/pairwise \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"drug_a_cid":"CID000000085","drug_b_cid":"CID000000119"}'
```

---

## 6. What's *not* built yet (don't design against these)

- **`drug_disease_flags` is always `[]`.** The query/cross-reference logic is real and wired up; it needs a curated, clinically-reviewed contraindication reference file that doesn't exist yet (see the note under `/predict/regimen` above). This backend will not fabricate that content.
- **No rate limiting anywhere.** Not implemented; needs an infra decision (in-memory vs. Redis-backed, per-IP vs. per-user limits) before it's built.
- **Pagination is now on the list endpoints that can grow** (`GET .../conditions`, `GET .../regimens`, `GET /vocab/drugs`) via `limit`/`offset` query params, but there's no cursor-based pagination or a `total` count in the response — a plain JSON array is returned, so "are there more pages" is inferred from whether you got back exactly `limit` results.
- **No patient *search*.** `GET /api/v1/patients` lists a clinician's assigned roster, but there's no server-side search by name or MRN — those columns are encrypted at rest with a non-deterministic cipher and can't be filtered on. Client-side filtering of a fetched page works; a global search needs a blind-index column added first.
- **No email-change flow.** `PATCH /patients/me` deliberately excludes email, because changing it also changes where consent codes go and needs new-address verification first.
- **`PatientRegimen` has no link back to `/predict/regimen`.** Adding a regimen via the API doesn't automatically run a prediction — the frontend still needs to separately call `/predict/regimen` with the cart's CIDs (fetched via `GET .../regimens`) if it wants risk scores for a patient's actual saved medication list.

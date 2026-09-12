# PharmacoGNN Frontend Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Deliver every guide-defined frontend route with live backend data where available and an explicit unavailable-capability state where a backend route is planned.

**Architecture:** A capability-aware API client owns transport, JWT/session state, error normalization, and exact endpoint contracts. Route controllers render only server responses; planned routes are real navigable screens whose adapters fail clearly rather than inventing clinical data. Shared shell code owns role visibility, deep-link return paths, and safety notices.

**Tech Stack:** Static HTML, vanilla JavaScript, CSS, Node.js built-in test runner, FastAPI REST API.

**Spec:** \`FRONTEND_GUIDE.md\` (user-provided integration guide).

## Global Constraints

- Never display synthetic or hardcoded patient, medication, interaction, report, transfer, or model-score data.
- Do not request an endpoint unless it is implemented in the backend; planned contracts show an explicit unavailable state.
- JWT role claims choose UI only. Backend responses remain authorization authority.
- Patient UI must not render clinician-only medical write controls.
- Make degraded model, disclaimer/model warning, unresolved drug, session expiry, 404/no-access, 422, and 429 states visible.
- Preserve the static HTML/vanilla JavaScript stack.

---

## File Structure

- \`frontend/js/api-client.js\`: transport, session, error model, capability table, endpoint wrappers.
- \`frontend/js/clinical-state.js\`: pure mappings from live API responses to page view models.
- \`frontend/js/route-guard.js\`: authentication, role gate, safe return-to handling.
- \`frontend/js/app-shell.js\`: role-aware navigation, shared status/banner UI.
- \`frontend/js/*-record.js\`, \`frontend/js/capability-page.js\`: route controllers with no fixtures.
- \`frontend/pages/*.html\`, \`frontend/css/clinical-app.css\`: screen markup and shared responsive styles.
- \`frontend/tests/*.test.cjs\`: client, view-model, routing, and no-fixture regression tests.

### Task 1: Capability-aware API client and session

**Files:**
- Modify: \`frontend/js/api-client.js\`
- Create: \`frontend/tests/api-client.test.cjs\`

**Interfaces:**
- Produces: \`ApiClient.request(path, options)\`, \`getSession()\`, \`getCapability(name)\`, \`getErrorMessage(error)\`.
- Produces wrappers for live auth, health, profiles, conditions, regimens, vocab, prediction, substitution, explanation.
- Planned report, transfer, invite, activation, and patient-list wrappers reject \`{ code: 'CAPABILITY_UNAVAILABLE', capability }\` without fetching.

- [ ] **Step 1: Write the failing tests**

\`\`\`js
test('normalizes a 429 into retry guidance', async () => {
  const error = await requestWith(fetch429).catch(error => error);
  assert.equal(error.code, 'RATE_LIMITED');
  assert.match(error.message, /try again/i);
});
test('does not fetch a planned report endpoint', async () => {
  await assert.rejects(ApiClient.getReport('r1'), { code: 'CAPABILITY_UNAVAILABLE' });
  assert.equal(fetchCalls, 0);
});
\`\`\`

- [ ] **Step 2: Run the focused tests**

Run: \`npm test -- tests/api-client.test.cjs\`

Expected: FAIL because the normalized error/capability API does not exist.

- [ ] **Step 3: Implement the minimal client**

Implement a safe base64url JWT payload decoder; refresh a valid token five minutes before \`exp\`; clear it only after an authenticated 401; normalize 404 to the guide copy, \`detail[]\` validation errors, and \`error\`/429 rate limits. Use a frozen capability map and exact live FastAPI payloads.

- [ ] **Step 4: Verify**

Run: \`npm test\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`bash
git add frontend/js/api-client.js frontend/tests/api-client.test.cjs
git commit -m "feat: add capability-aware frontend API client"
\`\`\`

### Task 2: Live clinical response models and safety notices

**Files:**
- Create: \`frontend/js/clinical-state.js\`
- Create: \`frontend/tests/clinical-state.test.cjs\`
- Modify: \`frontend/js/workspace-shared.js\`

**Interfaces:**
- Consumes: live \`PatientRegimenRead[]\`, \`RegimenPredictionResponse\`, \`PairwisePredictionResponse\`.
- Produces: \`createRegimenModel(regimens)\`, \`createPredictionModel(regimens, prediction)\`, \`safetyNotices(payload)\`.

- [ ] **Step 1: Write the failing tests**

\`\`\`js
test('maps a server matrix and never invents a diagonal score', () => {
  const model = createPredictionModel(regimens, { interaction_matrix: [[0, 81], [81, 0]], pairwise_flags: [] });
  assert.equal(model.cells[0][1].score, 81);
  assert.equal(model.cells[0][0].score, null);
});
test('turns degraded mode into a prominent notice', () => {
  assert.match(safetyNotices({ degraded_mode: true })[0].message, /unverified|degraded/i);
});
\`\`\`

- [ ] **Step 2: Run the focused tests**

Run: \`npm test -- tests/clinical-state.test.cjs\`

Expected: FAIL because \`clinical-state.js\` does not exist.

- [ ] **Step 3: Implement response-only models**

Source every matrix value from \`interaction_matrix\`; represent diagonal/absent/unavailable as \`null\`. Build notices only from returned fields: \`degraded_mode\`, report disclaimer/model warning, and unresolved drugs. Render all notice copy via \`textContent\`.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

\`\`\`bash
git add frontend/js/clinical-state.js frontend/js/workspace-shared.js frontend/tests/clinical-state.test.cjs
git commit -m "feat: map live clinical responses without fixtures"
\`\`\`

### Task 3: Role-aware shell, safe login, and deep links

**Files:**
- Create: \`frontend/js/route-guard.js\`
- Create: \`frontend/js/app-shell.js\`
- Create: \`frontend/css/clinical-app.css\`
- Create: \`frontend/tests/route-guard.test.cjs\`
- Modify: \`frontend/pages/login.html\`
- Modify: \`frontend/js/login.js\`

**Interfaces:**
- Produces: \`RouteGuard.requireAuth({ roles, returnTo })\`, \`AppShell.mount({ role, activeRoute })\`.

- [ ] **Step 1: Write the failing tests**

\`\`\`js
test('preserves a report deep link through login', () => {
  assert.equal(loginUrlFor('/pages/report.html?id=r1'), 'login.html?next=%2Fpages%2Freport.html%3Fid%3Dr1');
});
test('does not authorize patient UI for a clinician route', () => {
  assert.equal(canAccess({ role: 'PATIENT' }, ['CLINICIAN']), false);
});
\`\`\`

- [ ] **Step 2: Run the focused tests**

Run: \`npm test -- tests/route-guard.test.cjs\`

Expected: FAIL because route helpers do not exist.

- [ ] **Step 3: Implement shell and repair login**

Replace the old guard with route metadata. Make clinician registration pass literal \`CLINICIAN\` (the removed \`registerRole\` selector must not be read). Preserve pathname and query as \`next\`, reject off-origin/protocol-relative next values, and show links only after role inspection.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

\`\`\`bash
git add frontend/js/route-guard.js frontend/js/app-shell.js frontend/css/clinical-app.css frontend/js/login.js frontend/pages/login.html frontend/tests/route-guard.test.cjs
git commit -m "feat: add role-aware application shell"
\`\`\`

### Task 4: Replace the interaction workbench fixtures

**Files:**
- Modify: \`frontend/pages/workspace.html\`
- Modify: \`frontend/js/workspace.js\`, \`substitution-engine.js\`, \`pathway-inspector.js\`, \`demographic-lens.js\`, \`regimen-simulation.js\`
- Create: \`frontend/tests/interaction-workbench.test.cjs\`

**Interfaces:**
- Consumes: live API client prediction/vocabulary methods and \`ClinicalState\`.
- Produces: server-backed medicine search, regimen matrix, selected pair, explanation, and substitution UI.

- [ ] **Step 1: Write failing tests**

\`\`\`js
test('requests substitutions only for server-flagged high-risk pairs', async () => {
  await loadAlternatives({ is_high_risk: false });
  assert.equal(substituteCalls, 0);
});
test('maps explanation 502 to a visible unavailable state', () => {
  assert.match(explanationMessage({ status: 502 }).text, /unavailable/i);
});
\`\`\`

- [ ] **Step 2: Run focused tests**

Run: \`npm test -- tests/interaction-workbench.test.cjs\`

Expected: FAIL because the fixture store drives the workbench.

- [ ] **Step 3: Implement live-only controller behavior**

Remove all clinical fixture values and \`PharmaStore\` score reads from shipped workbench routes. Use vocabulary search to select known CIDs, live regimen prediction for the matrix, live pairwise prediction for ADRs, and call substitute only for \`is_high_risk\`. Use \`patient_id\` only for an actual record; otherwise send explicit \`patient_sex\`. Render degraded model, 502 explanation unavailable, no known pathway, validation error, failed fetch, and no alternatives.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

Manual check: with the backend on port 8000, authenticate, choose two vocabulary drugs, run a prediction, select a pair, and confirm an API failure never falls back to a score.

\`\`\`bash
git add frontend/pages/workspace.html frontend/js/workspace.js frontend/js/substitution-engine.js frontend/js/pathway-inspector.js frontend/js/demographic-lens.js frontend/js/regimen-simulation.js frontend/tests/interaction-workbench.test.cjs
git commit -m "feat: integrate live interaction workbench"
\`\`\`

### Task 5: Live patient record views

**Files:**
- Create: \`frontend/pages/patient-record.html\`, \`frontend/pages/my-record.html\`
- Create: \`frontend/js/patient-record.js\`, \`frontend/js/my-record.js\`
- Create: \`frontend/tests/patient-record.test.cjs\`

**Interfaces:**
- Consumes: live profile, conditions, regimens, and supported clinician write wrappers.
- Produces: clinician record UI and patient read-only record UI.

- [ ] **Step 1: Write failing tests**

\`\`\`js
test('patient role has no medical write actions', () => {
  assert.equal(recordActionsFor('PATIENT').includes('add-regimen'), false);
});
test('maps profile 404 to the agreed no-access copy', () => {
  assert.equal(patientErrorMessage(404), 'Not found, or you do not have access.');
});
\`\`\`

- [ ] **Step 2: Run focused tests**

Run: \`npm test -- tests/patient-record.test.cjs\`

Expected: FAIL because record action rules/controllers do not exist.

- [ ] **Step 3: Implement current patient API integration**

Render profile, conditions, and regimen from GET responses. Clinicians get only supported create/update actions; discontinuation uses \`PATCH { end_date }\`, while hard delete is never shown. Patients see medical fields read-only. Because the guide’s self-edit/onboarding/list contracts are not live, link to an explicit capability state instead of constructing fake records.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

\`\`\`bash
git add frontend/pages/patient-record.html frontend/pages/my-record.html frontend/js/patient-record.js frontend/js/my-record.js frontend/tests/patient-record.test.cjs
git commit -m "feat: add role-safe patient record screens"
\`\`\`

### Task 6: Complete planned-contract screen inventory

**Files:**
- Create: \`frontend/pages/patients.html\`, \`create-patient.html\`, \`activate.html\`, \`reports.html\`, \`report.html\`, \`transfers.html\`, \`care-team.html\`
- Create: \`frontend/js/capability-page.js\`
- Create: \`frontend/tests/capability-page.test.cjs\`

**Interfaces:**
- Consumes: \`ApiClient.getCapability(name)\`, planned wrappers, and \`RouteGuard\`.
- Produces: \`CapabilityPage.mount({ capability, title, requiredRole })\`.

- [ ] **Step 1: Write failing tests**

\`\`\`js
test('a planned report route does not render a fake report', () => {
  const model = pageModel('reports', false);
  assert.equal(model.state, 'unavailable');
  assert.equal(model.data, null);
});
test('retains report id on authenticated deep link', () => {
  assert.equal(returnToFor('/pages/report.html?id=r1'), '/pages/report.html?id=r1');
});
\`\`\`

- [ ] **Step 2: Run focused tests**

Run: \`npm test -- tests/capability-page.test.cjs\`

Expected: FAIL because capability-page model does not exist.

- [ ] **Step 3: Implement all screen routes**

Add clinician patient list/onboarding, activation, reports/history/detail/QR, transfers/consent, and care-team routes. Each calls its exact client wrapper and receives its required role gate. Until live, show no fake data, name the endpoint capability that is pending, and explain the user-facing impact. Retain \`?id=\`/ \`?token=\` only in URL/memory; never render invite tokens.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

\`\`\`bash
git add frontend/pages frontend/js/capability-page.js frontend/tests/capability-page.test.cjs
git commit -m "feat: add backend capability screen inventory"
\`\`\`

### Task 7: Fixture-removal proof and handoff documentation

**Files:**
- Modify: \`README.md\`, \`FRONTEND_GUIDE.md\`, \`frontend/js/workspace-shared.js\`, \`frontend/js/demo-store.js\`
- Create: \`frontend/tests/no-fixture-clinical-data.test.cjs\`

**Interfaces:**
- Produces a screen-to-endpoint matrix documenting live versus planned behavior.

- [ ] **Step 1: Write failing regression test**

\`\`\`js
test('live clinical controllers do not import demo fixtures', () => {
  for (const file of liveClinicalControllers) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), /PharmaStore|PharmaDemo/);
  }
});
\`\`\`

- [ ] **Step 2: Run focused test**

Run: \`npm test -- tests/no-fixture-clinical-data.test.cjs\`

Expected: FAIL until fixtures are detached from all live controllers.

- [ ] **Step 3: Remove unused demo dependency and document handoff**

Delete \`demo-store.js\` only after no shipped route imports it. Update README and the guide addendum with every screen, endpoint(s), backend status, and unavailable-state behavior. State that QR/invite workflows require configured \`FRONTEND_BASE_URL\` and CORS origin.

- [ ] **Step 4: Verify and commit**

Run: \`npm test\`

Run: \`rg -n "PharmaStore|PharmaDemo|Synthetic interaction score|demo-v0\\.1" frontend/pages frontend/js\`

Expected: tests PASS; no live-controller or user-visible synthetic-clinical result.

\`\`\`bash
git add README.md FRONTEND_GUIDE.md frontend/js frontend/tests
git commit -m "docs: record frontend backend integration status"
\`\`\`


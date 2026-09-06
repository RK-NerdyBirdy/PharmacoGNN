// Same real-CID lookup as workspace.js: static seed CIDs plus anything the
// user added via the real vocab search (persisted in workspace.js's
// DYNAMIC_CID_STORE_KEY). Kept local/duplicated rather than shared, matching
// this codebase's existing no-shared-config convention.
const PUBCHEM_CID_BY_MEDICINE_ID = { amitriptyline: 2160, citalopram: 2771 };
const DYNAMIC_CID_STORE_KEY = 'pharmagnn_medicine_cids';
function loadDynamicCidMap() {
  try { return JSON.parse(localStorage.getItem(DYNAMIC_CID_STORE_KEY) || '{}'); }
  catch { return {}; }
}
function getMedicineCid(medicineId) {
  return PUBCHEM_CID_BY_MEDICINE_ID[medicineId] || loadDynamicCidMap()[medicineId] || null;
}
const pairKey = (a, b) => [a, b].sort().join('|');

renderWorkspaceShell('Review & export');
const state = PharmaStore.getState();
const simulation = state.simulation;

// Renders one regimen's matrix from a real, already-fetched score map
// (pairKey -> score|null) instead of PharmaStore.score()'s synthetic demo
// fixture — mirrors UI.matrix()'s markup/classes so it looks identical, but
// nothing here is invented: a pair missing from the map (no real CID for
// one side, or the model call failed) honestly reads "?".
function renderRealMatrix(medicines, scoreMap) {
  const e = UI.escape;
  if (medicines.length < 2) return '<caption>Add at least two medicines to compare interactions.</caption>';
  return '<caption class="sr-only">Model-predicted pairwise interaction scores. Unknown does not mean safe.</caption><thead><tr><th scope="col">Drug</th>' +
    medicines.map((m, i) => '<th scope="col" title="' + e(m.name) + '">' + String.fromCharCode(65 + i) + '</th>').join('') +
    '</tr></thead><tbody>' + medicines.map((a, i) => '<tr><th scope="row" title="' + e(a.name) + '">' + String.fromCharCode(65 + i) + '</th>' +
      medicines.map((b) => {
        if (a.id === b.id) return '<td class="cell-diagonal">—</td>';
        const score = scoreMap[pairKey(a.id, b.id)] ?? null;
        const kind = PharmaDemo.classifyScore(score);
        const label = e(a.name + ' + ' + b.name + ': ' + (score == null ? 'unknown' : Math.round(score)) + '; ' + kind);
        return '<td class="cell-' + kind + '"><span aria-label="' + label + '">' + (score == null ? '?' : Math.round(score)) + '</span></td>';
      }).join('') + '</tr>').join('') + '</tbody>';
}

function coverage(medicines, scoreMap) {
  let scored = 0;
  const total = medicines.length * (medicines.length - 1) / 2;
  medicines.forEach((a, i) => medicines.slice(i + 1).forEach((b) => { if (scoreMap[pairKey(a.id, b.id)] != null) scored++; }));
  return { scored, total };
}

// Fetches real /predict/regimen scores for a medicine list. cidOverrides lets
// the proposed regimen supply the substitute candidate's real CID for its
// synthetic 'sub-<cid>' id, since that id obviously isn't in localStorage.
async function fetchScoreMap(medicines, cidOverrides = {}) {
  const eligible = medicines
    .map((m) => ({ m, cid: cidOverrides[m.id] || getMedicineCid(m.id) }))
    .filter((x) => x.cid);
  const map = {};
  if (eligible.length < 2 || !window.ApiClient || !ApiClient.isAuthenticated()) return map;
  try {
    const result = await ApiClient.predictRegimen({ drug_cids: eligible.map((x) => ApiClient.toModelCid(x.cid)) });
    eligible.forEach((row, i) => eligible.forEach((col, j) => {
      if (i === j) return;
      map[pairKey(row.m.id, col.m.id)] = result.interaction_matrix[i][j];
    }));
  } catch (err) {
    console.warn('Real regimen prediction unavailable for this comparison:', err.message);
  }
  return map;
}

if (!simulation) {
  UI.text('simulationSubtitle', 'Start by comparing an alternative against your current regimen.');
  document.getElementById('simulationContent').innerHTML = '<article class="ws-card empty-state"><h2>No simulation selected</h2><p>Choose a supported medicine pair, compare candidates, then simulate a change.</p><a class="btn btn-primary" href="substitution-engine.html">Compare candidates →</a></article>';
} else if (simulation.isReal) {
  // Real substitution, recorded by substitution-engine.js via
  // PharmaStore.setPendingSubstitution() — build both regimens and fetch
  // real model scores for each rather than reusing the demo score fixture.
  const { candidate, replacedMedicineId, fixedMedicineId } = simulation;
  const replaced = state.medicines.find((m) => m.id === replacedMedicineId);
  const proposedId = 'sub-' + candidate.cid;
  const proposedMedicines = state.medicines.map((m) =>
    m.id === replacedMedicineId ? { id: proposedId, name: candidate.name, dose: 'Requires review' } : m
  );

  UI.text('simulationSubtitle', (replaced ? replaced.name : 'the original drug') + ' → ' + candidate.name + ' — real model-predicted comparison.');
  document.getElementById('simulationContent').innerHTML = '<article class="ws-card empty-state"><h2>Loading real model predictions…</h2><p>Fetching predicted interaction scores for both regimens.</p></article>';

  (async () => {
    const [originalMap, proposedMap] = await Promise.all([
      fetchScoreMap(state.medicines),
      fetchScoreMap(proposedMedicines, { [proposedId]: candidate.cid }),
    ]);
    const e = UI.escape;
    const originalPairScore = replaced ? originalMap[pairKey(replacedMedicineId, fixedMedicineId)] ?? null : null;
    const proposedPairScore = proposedMap[pairKey(proposedId, fixedMedicineId)] ?? null;
    const cOriginal = coverage(state.medicines, originalMap);
    const cProposed = coverage(proposedMedicines, proposedMap);

    document.getElementById('simulationContent').innerHTML =
      '<section class="ws-card simulation-summary"><div><span class="context-label">SELECTED PAIR SCORE</span><strong class="summary-score">' +
        (originalPairScore == null ? '?' : Math.round(originalPairScore)) + ' → ' + (proposedPairScore == null ? '?' : Math.round(proposedPairScore)) +
      '</strong></div>' +
      (originalPairScore != null && proposedPairScore != null
        ? '<span class="pill '+(proposedPairScore<=originalPairScore?'good-pill':'pill-muted')+'">' + (Math.round(proposedPairScore - originalPairScore)) + ' points</span>'
        : '<span class="pill pill-muted">No real score for this pair</span>') +
      '<div><span class="context-label">COVERAGE</span><strong>' + cProposed.scored + ' of ' + cProposed.total + ' pairs scored</strong></div></section>' +
      '<section class="simulation-grid">' + [[state.medicines, originalMap, 'Original regimen'], [proposedMedicines, proposedMap, 'Proposed draft']]
        .map(([medicines, scoreMap, title]) =>
          '<article class="ws-card"><header class="ws-card-header"><h2>' + title + '</h2><p class="ws-card-note">' + e(medicines.map((m) => m.name).join(' · ')) + '</p></header><div class="matrix-wrap"><table class="interaction-matrix">' + renderRealMatrix(medicines, scoreMap) + '</table></div><p class="matrix-key">' + e(UI.key(medicines)) + '</p></article>'
        ).join('') + '</section>';
  })();
} else {
  // Legacy synthetic simulation shape (demo-store.js's simulate(), still used
  // by its own test suite) — unchanged behavior for that path.
  const { candidate, original, proposed } = simulation, c = coverage(proposed.medicines, proposed.scores || {}), e = UI.escape;
  UI.text('simulationSubtitle', candidate.name + ' replaces amitriptyline in an illustrative draft regimen.');
  document.getElementById('simulationContent').innerHTML = '<section class="ws-card simulation-summary"><div><span class="context-label">SELECTED PAIR SCORE</span><strong class="summary-score">82 → ' + candidate.score + '</strong></div><span class="pill good-pill">' + (candidate.score - 82) + ' points</span><div><span class="context-label">COVERAGE</span><strong>' + c.scored + ' of ' + c.total + ' pairs scored</strong></div></section><section class="simulation-grid">' + [[original, 'Original regimen'], [proposed, 'Proposed draft']].map(([regimen, title]) => '<article class="ws-card"><header class="ws-card-header"><h2>' + title + '</h2><p class="ws-card-note">' + e(regimen.medicines.map((m) => m.name).join(' · ')) + '</p></header><div class="matrix-wrap"><table class="interaction-matrix">' + UI.matrix(regimen) + '</table></div><p class="matrix-key">' + e(UI.key(regimen.medicines)) + '</p></article>').join('') + '</section>';
}

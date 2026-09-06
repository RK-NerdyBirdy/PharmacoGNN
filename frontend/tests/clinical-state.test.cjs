const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createPredictionModel, safetyNotices } = require('../js/clinical-state.js');

const regimen = [
  { id: 'a', pubchem_cid: 85, drug_name: 'Drug A', end_date: null },
  { id: 'b', pubchem_cid: 119, drug_name: 'Drug B', end_date: null },
];

test('maps server matrix cells and never invents a diagonal score', () => {
  const model = createPredictionModel(regimen, { interaction_matrix: [[0, 81], [81, 0]], pairwise_flags: [] });
  assert.equal(model.cells[0][1].score, 81);
  assert.equal(model.cells[0][0].score, null);
});

test('turns degraded model mode into a visible safety notice', () => {
  const [notice] = safetyNotices({ degraded_mode: true });
  assert.equal(notice.level, 'warning');
  assert.match(notice.message, /unverified|degraded/i);
});

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { pageModel } = require('../js/capability-page.js');

test('planned workflow displays unavailable state without fabricated data', () => {
  assert.deepEqual(pageModel('reports', false), { state: 'unavailable', data: null });
});

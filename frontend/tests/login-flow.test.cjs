const { test } = require('node:test');
const assert = require('node:assert/strict');
const { clinicianRegistration } = require('../js/login-flow.js');

test('builds a clinician-only registration payload without a role selector', () => {
  assert.deepEqual(clinicianRegistration(' doctor@example.com ', 'password123'), {
    email: 'doctor@example.com', password: 'password123', role: 'CLINICIAN'
  });
});

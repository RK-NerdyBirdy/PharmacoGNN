const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createApiClient } = require('../js/api-client.js');

function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}

test('turns an API rate limit into actionable retry guidance', async () => {
  const client = createApiClient({
    fetch: async () => new Response(JSON.stringify({ error: 'Rate limit exceeded: login' }), { status: 429 }),
    storage: storage(),
  });

  await assert.rejects(client.request('/api/v1/auth/login', { auth: false }), error => {
    assert.equal(error.code, 'RATE_LIMITED');
    assert.match(error.message, /try again/i);
    return true;
  });
});

test('reports is a live capability: getReport calls the real endpoint', async () => {
  let requestedUrl = null;
  const client = createApiClient({
    fetch: async (url) => { requestedUrl = url; return new Response(JSON.stringify({ id: 'report-1', status: 'complete' }), { status: 200 }); },
    storage: storage(),
  });

  const result = await client.getReport('report-1');
  assert.equal(result.id, 'report-1');
  assert.match(requestedUrl, /\/api\/v1\/reports\/report-1$/);
});

test('still rejects a not-yet-built capability (activation) without a request', async () => {
  let requests = 0;
  const client = createApiClient({
    fetch: async () => { requests += 1; throw new Error('network should not be used'); },
    storage: storage(),
  });

  await assert.rejects(client.activateAccount(), error => {
    assert.equal(error.code, 'CAPABILITY_UNAVAILABLE');
    assert.equal(error.capability, 'activation');
    return true;
  });
  assert.equal(requests, 0);
});

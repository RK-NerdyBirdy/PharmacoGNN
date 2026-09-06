const { test } = require('node:test');
const assert = require('node:assert/strict');
const { logout } = require('../js/logout-flow.js');

test('clears the API session and returns to sign in', () => {
  let cleared = false;
  const location = { href: 'workspace.html' };
  logout({ logout: () => { cleared = true; } }, location);
  assert.equal(cleared, true);
  assert.equal(location.href, 'login.html');
});

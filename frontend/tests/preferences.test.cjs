const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createPreferences } = require('../js/preferences.js');

function memory() {
  const values = new Map();
  return {
    getItem: key => values.get(key),
    setItem: (key, value) => values.set(key, value)
  };
}

test('preferences default safely and persist independently', () => {
  const storage = memory();
  const preferences = createPreferences(storage);
  assert.deepEqual(preferences.get(), { language: 'en', theme: 'pink' });
  preferences.save({ language: 'hi', theme: 'dark' });
  assert.deepEqual(createPreferences(storage).get(), { language: 'hi', theme: 'dark' });
});

test('invalid stored or saved preferences fall back to supported defaults', () => {
  const storage = { getItem: () => '{invalid', setItem: () => {} };
  assert.deepEqual(createPreferences(storage).get(), { language: 'en', theme: 'pink' });
  assert.deepEqual(createPreferences(memory()).save({ language: 'xx', theme: 'orange' }), { language: 'en', theme: 'pink' });
});

test('translations retain interpolated clinical values unchanged', () => {
  const preferences = createPreferences(memory());
  preferences.save({ language: 'ta', theme: 'dark' });
  assert.equal(preferences.t('workspace.selectedPair', { pair: 'Amitriptyline × Citalopram' }), 'தேர்ந்தெடுத்த ஜோடி: Amitriptyline × Citalopram');
});

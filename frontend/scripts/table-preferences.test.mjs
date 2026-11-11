import test from 'node:test';
import assert from 'node:assert/strict';
import { filterAndSortRows, normalizeTablePreferences, readTablePreferences, tablePreferenceKey, writeTablePreferences } from '../src/utils/tablePreferences.js';

const defaults = { columns: ['name', 'quantity'], sorts: ['', 'name', '-name', 'quantity', '-quantity'], sort: '', pageSize: 10, filters: { status: '' } };
test('table settings are isolated by account and table, and restore all display preferences', () => {
  const data = new Map(), storage = { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value) };
  const first = tablePreferenceKey(1, 'samples'), value = { query: 'protein', sort: '-name', page: 3, pageSize: 25, columns: ['name'], filters: { status: 'QC' } };
  assert.equal(writeTablePreferences(storage, first, value), true);
  assert.deepEqual(readTablePreferences(storage, first, defaults), value);
  assert.equal(readTablePreferences(storage, tablePreferenceKey(2, 'samples'), defaults).query, '');
  assert.equal(readTablePreferences(storage, tablePreferenceKey(1, 'inventory-lots'), defaults).query, '');
});

test('malformed, obsolete or unsafe settings fall back to allowed display options', () => {
  const result = normalizeTablePreferences({ query: [], sort: 'created_by__password', page: -1, pageSize: 10000, columns: ['missing'], filters: { status: {}, secret: 'private' } }, defaults);
  assert.deepEqual(result, { query: '', sort: '', page: 1, pageSize: 10, columns: ['name', 'quantity'], filters: { status: '' } });
  assert.equal(tablePreferenceKey(null, 'samples'), null);
  assert.equal(tablePreferenceKey(1, '../other'), null);
  assert.deepEqual(readTablePreferences({ getItem: () => '{bad' }, 'key', defaults), normalizeTablePreferences(null, defaults));
  assert.equal(writeTablePreferences({ setItem() { throw new Error('Blocked'); } }, 'key', result), false);
});

test('filtering and numeric sorting preserve original rows and keep missing values last', () => {
  const rows = [{ id: 1, name: 'Protein 10', quantity: 10, status: 'QC' }, { id: 2, name: 'Protein 2', quantity: 2, status: 'QC' }, { id: 3, name: 'DNA', quantity: null, status: 'NEW' }];
  const columns = ['name', 'quantity', 'status'].map(key => ({ key, value: row => row[key] }));
  const preferences = { query: 'protein', sort: 'name', filters: { status: 'QC' } };
  assert.deepEqual(filterAndSortRows(rows, columns, preferences).map(row => row.id), [2, 1]);
  assert.deepEqual(filterAndSortRows(rows, columns, { query: '', sort: '-quantity', filters: {} }).map(row => row.id), [1, 2, 3]);
  assert.deepEqual(rows.map(row => row.id), [1, 2, 3]);
});

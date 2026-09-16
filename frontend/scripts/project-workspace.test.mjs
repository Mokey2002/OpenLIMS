import test from 'node:test';
import assert from 'node:assert/strict';
import { filterProjectSamples } from '../src/pages/projectWorkspace.js';

const samples = [
  { id: 1, sample_id: 'S-101', status: 'QC', container_code: 'Freezer-A' },
  { id: 2, sample_id: 'S-102', status: 'RECEIVED', container_code: null },
];
test('empty search keeps the supplied project sample list', () => {
  assert.deepEqual(filterProjectSamples(samples, '  '), samples);
});
test('matches identifier, status and container without case sensitivity', () => {
  for (const query of [' s-101 ', 'qc', 'freezer-a']) {
    assert.deepEqual(filterProjectSamples(samples, query), [samples[0]]);
  }
});
test('handles missing values and unmatched searches', () => {
  assert.deepEqual(filterProjectSamples(samples, 'missing'), []);
  assert.deepEqual(filterProjectSamples([], 'qc'), []);
  assert.deepEqual(filterProjectSamples([{}], 'qc'), []);
});

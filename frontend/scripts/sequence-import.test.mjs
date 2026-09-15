import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSingleSequence, selectedSequence } from '../src/utils/sequenceImport.js';

test('FASTA headers are excluded and multiline bases normalized', () => {
  assert.deepEqual(parseSingleSequence('\uFEFF>Example\r\nacgt\r\n nry\n', 'DNA'), {name:'Example', sequence:'ACGTNRY'});
  assert.deepEqual(parseSingleSequence(' acgu\nN ', 'RNA'), {name:'', sequence:'ACGUN'});
  assert.equal(parseSingleSequence('>protein\nMKW*', 'PROTEIN').sequence, 'MKW*');
});
test('rejects multiple records and invalid or empty sequences without concatenating them', () => {
  for (const text of ['>one\nACG\n>two\nTTT', 'ACG\n>one\nTTT', '>empty', 'ACG123', 'ACGU']) {
    assert.throws(() => parseSingleSequence(text, 'DNA'));
  }
});
test('copy uses zero-based exclusive end and rejects invalid or wrapped ranges', () => {
  assert.equal(selectedSequence('ACGTAC', {start:1,end:4}), 'CGT');
  for(const selection of [null, {start:-1,end:2}, {start:0,end:7}, {start:4,end:1}, {start:2,end:2}, {start:0.5,end:3}]) {
    assert.equal(selectedSequence('ACGTAC', selection), '');
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, controlValidationMessage, flattenValidationErrors, responseError } from '../src/utils/formErrors.js';
import { notebookEditAccess } from '../src/utils/actionGuidance.js';

test('nested validation errors retain exact control paths and separate form-level errors', () => {
  const result = flattenValidationErrors({ sample_id: ['Already registered.'], form_values: { concentration: ['Above the limit.'] }, measurements: [{ value: ['Invalid reading.'] }], non_field_errors: ['Choose a lot or barcode.'] });
  assert.deepEqual(result.fields['sample_id'], ['Already registered.']);
  assert.deepEqual(result.fields['form_values.concentration'], ['Above the limit.']);
  assert.deepEqual(result.fields['measurements.0.value'], ['Invalid reading.']);
  assert.deepEqual(result.general, ['Choose a lot or barcode.']);
});

test('malformed or hostile error keys cannot alter prototypes or crash rendering', () => {
  const parsed = flattenValidationErrors(JSON.parse('{"__proto__":{"polluted":"yes"},"toString":["Invalid value"],"field":null}'));
  assert.equal({}.polluted, undefined);
  assert.deepEqual(parsed.fields.toString, ['Invalid value']);
  assert.equal(Object.keys(flattenValidationErrors(null).fields).length, 0);
  assert.equal(Object.keys(flattenValidationErrors({ field: Array.from({ length: 1000 }, () => 'Error') }).fields).length, 1);
  assert.equal(flattenValidationErrors({ field: Array.from({ length: 1000 }, () => 'Error') }).fields.field.length, 100);
});

test('server errors and proxy HTML are hidden while validation and status stay usable', async () => {
  const error = await responseError(new Response('<html>Traceback: internal private path</html>', { status: 500 }));
  assert.equal(error.status, 500);
  assert.doesNotMatch(error.message, /Traceback|private path|html/);
  const invalid = new ApiError(400, { email: ['Invalid address.'] });
  assert.deepEqual(invalid.fieldErrors.email, ['Invalid address.']);
  assert.equal(invalid.status, 400);
  assert.match(new ApiError(0).message, /confirm the request/);
});

test('client constraints preserve valid scientific zero and explicit false values', () => {
  const valid = { willValidate: true, validity: { valid: true }, required: true, minLength: -1 };
  assert.equal(controlValidationMessage({ ...valid, value: '0', type: 'number' }), '');
  assert.equal(controlValidationMessage({ ...valid, value: 'false', type: 'select-one' }), '');
  assert.equal(controlValidationMessage({ ...valid, value: '', validity: { valueMissing: true } }), 'Enter or select a value.');
  assert.match(controlValidationMessage({ ...valid, value: 'x', type: 'email', validity: { typeMismatch: true } }), /name@example.org/);
  assert.match(controlValidationMessage({ ...valid, value: '1', min: '2', type: 'number', validity: { rangeUnderflow: true } }), /at least 2/);
  assert.equal(controlValidationMessage({ willValidate: false }), '');
});

test('notebook guidance distinguishes access, immutable state, completion and unknown state', () => {
  assert.equal(notebookEditAccess({ status: 'DRAFT', permissions: { write: true }, roles: ['viewer'] }).allowed, true);
  assert.match(notebookEditAccess({ status: 'DRAFT', permissions: { write: false } }).reason, /edit access/);
  assert.match(notebookEditAccess({ status: 'LOCKED', permissions: { write: true } }).next_step, /Clone/);
  assert.match(notebookEditAccess({ status: 'LOCKED', permissions: { write: false } }).next_step, /owner/);
  assert.match(notebookEditAccess({ status: 'COMPLETED', permissions: { write: true } }).reason, /awaiting review/);
  assert.match(notebookEditAccess({ status: 'UNKNOWN', permissions: { write: true } }).reason, /unavailable/);
});

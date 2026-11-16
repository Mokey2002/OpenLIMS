import test from 'node:test';
import assert from 'node:assert/strict';
import { sampleNextStep } from '../src/utils/sampleNextStep.mjs';
const runs = (...statuses) => [{ status: 'ACTIVE', steps: statuses.map(status => ({ status })) }];

test('failed and quality-gated steps take priority over other ready work', () => {
  assert.equal(sampleNextStep({ status: 'IN_PROGRESS' }, [], runs('READY', 'FAILED')), 'failed');
  assert.equal(sampleNextStep({ status: 'IN_PROGRESS' }, [], runs('READY', 'AWAITING_QC')), 'review');
  assert.equal(sampleNextStep({ status: 'IN_PROGRESS' }, [], runs('READY', 'IN_PROGRESS')), 'continue');
});
test('terminal records and historical pipelines do not suggest starting work', () => {
  assert.equal(sampleNextStep({ status: 'ARCHIVED' }, [], runs('READY')), 'archived');
  assert.equal(sampleNextStep({ status: 'CANCELLED' }, ['ARCHIVED'], runs('FAILED')), 'cancelled');
  assert.equal(sampleNextStep({ status: 'RECEIVED' }, [], [{ status: 'COMPLETED', steps: [{ status: 'FAILED' }] }]), 'received');
});
test('blocked runs and custom policies do not invent a next transition', () => {
  assert.equal(sampleNextStep({ status: 'IN_PROGRESS' }, [], runs('BLOCKED')), 'blocked');
  assert.equal(sampleNextStep({ status: 'LAB_HOLD' }, ['QC']), 'custom');
  assert.equal(sampleNextStep({ status: 'LAB_HOLD' }, []), 'noTransition');
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { prioritizeWork, workAction } from '../src/utils/workPriorities.mjs';

test('overdue work precedes review work; upcoming work follows due date without changing input', () => {
  const rows = [
    { id: 'later', due_at: '2030-06-01' },
    { id: 'review', qc_status: 'PENDING_REVIEW' },
    { id: 'overdue', due_at: '2020-01-01' },
    { id: 'soon', due_at: '2030-01-01' },
  ];
  assert.deepEqual(prioritizeWork(rows, Date.parse('2026-01-01')).map(x => x.id), ['overdue', 'review', 'soon', 'later']);
  assert.equal(rows[0].id, 'later');
});

test('failed or rerun work leads to work queue rather than suggesting QC approval', () => {
  assert.deepEqual(workAction({ qc_status: 'RERUN_REQUIRED' }), { label: 'Review and retry work', to: '/work-queue' });
  assert.equal(workAction({ status: 'FAILED' }).to, '/work-queue');
  assert.equal(workAction({ qc_status: 'PENDING_REVIEW' }).to, '/qc-review');
});

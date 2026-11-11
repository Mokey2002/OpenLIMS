import test from 'node:test';
import assert from 'node:assert/strict';
import { draftContent, notebookDraftKey, readNotebookDraft, removeNotebookDraft, sameDraftContent, storeNotebookDraft } from '../src/utils/notebookRecovery.js';

const memory = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }; };
const content = { blocks: [{ _key: 'temporary', public_id: 'old-block', block_type: 'RICH_TEXT', data: { text: 'Protein μg/mL 🧪' } }], links: [{ entity_type: 'sample', public_id: 'sample-a', relation_type: 'used', label: 'Sample A', version: {} }] };

test('drafts survive a page reload but remain scoped to one user and experiment', () => {
  const storage = memory(), key = notebookDraftKey(7, 'experiment-a');
  assert.equal(storeNotebookDraft(storage, key, content, 'revision-one', 1000), true);
  const recovered = readNotebookDraft(storage, key, 1001);
  assert.equal(recovered.blocks[0].data.text, 'Protein μg/mL 🧪');
  assert.equal(recovered.baseRevision, 'revision-one');
  assert.equal(readNotebookDraft(storage, notebookDraftKey(8, 'experiment-a'), 1001), null);
  assert.equal(readNotebookDraft(storage, notebookDraftKey(7, 'experiment-b'), 1001), null);
  assert.equal(recovered.blocks[0]._key, undefined);
});

test('equivalent committed content ignores temporary keys, object order, captured labels and link order', () => {
  const left = draftContent(content.blocks, [...content.links, { entity_type: 'sample', public_id: 'sample-b', relation_type: 'used' }]);
  const right = structuredClone(left);
  right.links.reverse(); right.links[1].label = 'Renamed sample'; right.links[1].version = { checksum: 'new' };
  assert.equal(sameDraftContent(left, right), true);
  right.blocks[0].data.text = 'Another scientist edited this';
  assert.equal(sameDraftContent(left, right), false);
});

test('storage failures and oversized drafts are reported without pretending a recovery copy exists', () => {
  const blocked = { setItem() { throw new Error('Quota'); }, getItem() { throw new Error('Blocked'); } };
  assert.equal(storeNotebookDraft(blocked, notebookDraftKey(7, 'experiment-a'), content, ''), false);
  assert.equal(readNotebookDraft(blocked, notebookDraftKey(7, 'experiment-a')), null);
  assert.equal(storeNotebookDraft(memory(), notebookDraftKey(7, 'experiment-a'), { blocks: [{ block_type: 'RICH_TEXT', data: { text: 'x'.repeat(3 * 1024 * 1024) } }], links: [] }, ''), false);
});

test('expired or malformed recovery records cannot be restored', () => {
  const storage = memory(), key = notebookDraftKey(7, 'experiment-a');
  storeNotebookDraft(storage, key, content, '', 1000);
  assert.equal(readNotebookDraft(storage, key, 1000 + 8 * 24 * 60 * 60 * 1000), null);
  for (const value of ['{bad', 'null', '[]', JSON.stringify({ version: 1, savedAt: 1000, baseRevision: '', blocks: [null], links: [] })]) {
    storage.setItem(key, value);
    assert.equal(readNotebookDraft(storage, key, 1000), null);
  }
});

test('confirmed save clears only the matching recovery copy', () => {
  const storage = memory(), first = notebookDraftKey(7, 'experiment-a'), second = notebookDraftKey(8, 'experiment-a');
  storeNotebookDraft(storage, first, content, 'r1'); storeNotebookDraft(storage, second, content, 'r1');
  removeNotebookDraft(storage, first);
  assert.equal(readNotebookDraft(storage, first), null);
  assert.ok(readNotebookDraft(storage, second));
  assert.equal(notebookDraftKey(null, 'experiment-a'), null);
});

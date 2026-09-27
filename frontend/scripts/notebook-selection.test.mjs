import test from 'node:test';
import assert from 'node:assert/strict';
import { selectNotebookRecord } from '../src/pages/notebookSelection.js';
const notebooks = [{id:1}, {id:2}];
const experiments = [{id:11, public_id:'first', notebook:1}, {id:22, public_id:'second', notebook:2}];
const choose = params => selectNotebookRecord({notebooks, experiments, ...params});
test('opens UUID link in correct notebook', () => {
  const result=choose({experimentId:'second', strict:true});
  assert.equal(result.notebook.id,2); assert.equal(result.experiment.id,22);
});
test('missing or inaccessible experiment does not open another record', () => {
  assert.deepEqual(choose({experimentId:'missing', strict:true}), {notebook:null, experiment:null, unavailable:true});
});
test('missing notebook does not fall back to first notebook', () => {
  assert.equal(choose({notebookId:'999', strict:true}).unavailable,true);
});
test('ordinary workspace and explicit notebook selection keep their defaults', () => {
  assert.equal(choose({}).experiment.id,11);
  assert.equal(choose({notebookId:2}).experiment.id,22);
  assert.equal(selectNotebookRecord({notebooks:[], experiments:[]}).experiment,null);
});

test('switching notebooks does not retain experiment from previous notebook', () => {
  const result=choose({notebookId:2, experimentId:11});
  assert.equal(result.notebook.id,2); assert.equal(result.experiment.id,22);
});

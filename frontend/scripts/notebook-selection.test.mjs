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

test('numeric and string IDs resolve to the same experiment', () => {
  for (const experimentId of [22, '22', 'second']) {
    assert.equal(choose({experimentId, strict:true}).experiment.id,22);
  }
});

test('an experiment whose notebook is inaccessible cannot be opened', () => {
  const result=selectNotebookRecord({notebooks:[{id:1}], experiments, experimentId:'second', strict:true});
  assert.deepEqual(result,{notebook:null, experiment:null, unavailable:true});
});

test('empty notebook does not borrow an experiment from another notebook', () => {
  const result=selectNotebookRecord({notebooks:[{id:3}, ...notebooks], experiments, notebookId:3, strict:true});
  assert.equal(result.notebook.id,3);
  assert.equal(result.experiment,null);
  assert.equal(result.unavailable,false);
});

test('selection does not mutate cached API records', () => {
  const frozenNotebooks=Object.freeze(notebooks.map(row=>Object.freeze({...row})));
  const frozenExperiments=Object.freeze(experiments.map(row=>Object.freeze({...row})));
  const before=JSON.stringify({frozenNotebooks,frozenExperiments});
  selectNotebookRecord({notebooks:frozenNotebooks, experiments:frozenExperiments, experimentId:'second', strict:true});
  assert.equal(JSON.stringify({frozenNotebooks,frozenExperiments}),before);
});

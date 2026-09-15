import test from 'node:test';
import assert from 'node:assert/strict';
import { initialHistory, workspaceHistory as reduce } from '../src/utils/workspaceHistory.js';
const initial = {name:'Original',annotations:[]};
test('feature edits undo and redo without mutating saved snapshots', () => {
 let s = initialHistory(initial);
 s = reduce(s,{type:'set',key:'annotations',value:old=>[...old,{name:'Gene',start:0,end:3}]});
 assert.equal(initial.annotations.length,0);
 s = reduce(s,{type:'undo'}); assert.deepEqual(s.value,initial);
 s = reduce(s,{type:'redo'}); assert.equal(s.value.annotations[0].name,'Gene');
 s = reduce(s,{type:'undo'}); s=reduce(s,{type:'set',key:'name',value:'New'});assert.equal(s.future.length,0);
});
test('save completion does not mark newer edits as saved', () => {
 let s = initialHistory(initial); const submitted=s.value;
 s=reduce(s,{type:'set',key:'name',value:'Later edit'});
 s=reduce(s,{type:'saved',value:submitted});assert.notEqual(JSON.stringify(s.value),s.saved);
});
test('loading checkpoint prevents undo into a different workspace', () => {
 let s=reduce(initialHistory(initial),{type:'set',key:'name',value:'Loaded'});
 s=reduce(s,{type:'checkpoint'});assert.equal(s.past.length,0);assert.equal(JSON.stringify(s.value),s.saved);
 assert.equal(reduce(s,{type:'undo'}),s);
});

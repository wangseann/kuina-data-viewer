'use strict';
const assert = require('node:assert/strict');
const T = require('../docs/tasks-core.js');
const people = ['juan','emily','brian','amir','seann','taha','saswato','th','jion'].map(id => ({id,name:id,queued:0,active:0,awaiting_verification:0,verified:0,load:0}));
const task = {id:'task_123',category:'stocks',kind:'triage',status:'queued',assignee:'juan',effort:1,affected_series:42,issues:['short_history'],created_at:'2026-11-11T00:00:00Z',updated_at:'2026-11-11T00:00:00Z'};
const snapshot = {schema_version:1,updated_at:'2026-11-11T00:00:00Z',profile:{max_interval_seconds:900,min_years:2,unexplained_gaps_allowed:0},people,tasks:[task]};
assert.equal(T.validate(snapshot).tasks.length,1);
assert.throws(() => T.validate({...snapshot,private_paths:['secret']}));
assert.throws(() => T.validate({...snapshot,tasks:[{...task,note:'private target'}]}));
assert.throws(() => T.validate({...snapshot,profile:{...snapshot.profile,max_interval_seconds:3600}}));
assert.throws(() => T.validate({...snapshot,tasks:[{...task,assignee:'stranger'}]}));
assert.throws(() => T.validate({...snapshot,tasks:[task,task]}));
assert.equal(T.matches(task,{person:'emily',category:'all',status:'all'}),false);
assert.equal(T.matches(task,{person:'juan',category:'stocks',status:'queued'}),true);
assert.equal(T.stale(snapshot.updated_at,Date.parse('2026-11-12T01:00:00Z')),true);
assert.equal(T.stale(snapshot.updated_at,Date.parse('2026-11-11T01:00:00Z')),false);
console.log('Task board privacy, profile and filter checks passed');

const parent={...task,id:'triage-parent',status:'batched',affected_series:3,lead:'juan',parent_id:null,batch_number:0,batch_total:2};
const child1={...task,id:'batch-one',assignee:'emily',affected_series:2,lead:'juan',parent_id:parent.id,batch_number:1,batch_total:2};
const child2={...child1,id:'batch-two',assignee:'brian',affected_series:1,batch_number:2};
const batchPeople=people.map(p=>({...p,batched:p.id==='juan'?1:0,queued:['emily','brian'].includes(p.id)?1:0,load:['emily','brian'].includes(p.id)?1:0,remaining_series:p.id==='emily'?2:p.id==='brian'?1:0}));
const batched={...snapshot,schema_version:2,batch_limit:500,people:batchPeople,tasks:[parent,child1,child2]};
assert.equal(T.validate(batched).tasks.length,3);
assert.throws(()=>T.validate({...batched,tasks:[parent,{...child1,affected_series:501},child2]}));
assert.throws(()=>T.validate({...batched,tasks:[parent,child1,{...child2,batch_number:1}]}));
assert.throws(()=>T.validate({...batched,people:batchPeople.map(p=>({...p,remaining_series:99}))}));
assert.equal(T.reviewTasks(batched,{person:'all',category:'all',status:'all'}).length,2);
assert.equal(T.page(Array.from({length:91},(_,i)=>i),1).rows.length,40);
assert.deepEqual(T.page([1,2],100).rows,[1,2]);
const rollup=T.rollups(batched)[0];
assert.equal('lead' in rollup,false);assert.equal(rollup.batches,2);assert.equal(rollup.records,3);
assert.equal(T.remaining(snapshot.people[0],snapshot),42);
console.log('Bounded batch validation, continuity, workload and pagination checks passed');

const manualTasks=batched.tasks.map(t=>{
  const {lead,effort,...rest}=t;
  return {...rest,assignee:null,status:t.status==='batched'?'batched':'available',assignment_issue:null};
});
const manualPeople=people.map(p=>({id:p.id,name:p.name,assigned:0,active:0,awaiting_verification:0,verified:0,remaining_series:0}));
const manual={...batched,schema_version:3,people:manualPeople,tasks:manualTasks};
assert.equal(T.validate(manual).tasks.length,3);
assert.equal(T.availableRecords(manual),3);
assert.throws(()=>T.validate({...manual,tasks:[{...manualTasks[0],lead:'juan'},...manualTasks.slice(1)]}));
assert.throws(()=>T.validate({...manual,tasks:[manualTasks[0],{...manualTasks[1],assignee:'juan'},manualTasks[2]]}));
const url=new URL(T.requestURL(manualTasks[1],'seann','assign'));
assert.equal(url.hostname,'github.com');assert.equal(url.pathname,'/wangseann/kuina-data-viewer/issues/new');
const request=JSON.parse(url.searchParams.get('body').split('<!-- kuina-request-v1\n')[1].split('\n-->')[0]);
assert.deepEqual(request,{version:1,action:'assign',task_id:'batch-one',person:'seann'});
assert.throws(()=>T.requestURL(manualTasks[1],'stranger','assign'));
assert.equal(T.reviewTasks(manual,{person:'all',category:'all',status:'available'}).length,2);
console.log('Self-service privacy, availability and GitHub request contract checks passed');

const assigned={...manualTasks[1],status:'assigned',assignee:'seann',assignment_issue:81};
const releaseURL=new URL(T.requestURL(assigned,'seann','release'));
assert.equal(releaseURL.searchParams.get('title'),'[Kuina release] batch-one');
const releaseRequest=JSON.parse(releaseURL.searchParams.get('body').split('<!-- kuina-request-v1\n')[1].split('\n-->')[0]);
assert.deepEqual(releaseRequest,{version:1,action:'release',task_id:'batch-one',person:'seann',assignment_issue:81});
assert.throws(()=>T.requestURL({...assigned,assignment_issue:null},'seann','release'));
assert.throws(()=>T.requestURL({...assigned,assignment_issue:0},'seann','release'));
assert.throws(()=>T.requestURL({...assigned,status:'active'},'seann','release'));
assert.throws(()=>T.requestURL(assigned,'juan','release'));
console.log('Release requests bind the exact assignment issue and unstarted owner');

// Both complete rosters are readable during rollout; arbitrary subsets fail closed.
const addedPeople=['vitoria','olga'].map(id=>({id,name:id==='vitoria'?'Vitoria':'Olga',assigned:0,active:0,awaiting_verification:0,verified:0,remaining_series:0}));
const expanded={...manual,people:[...manual.people,...addedPeople]};
assert.equal(T.validate(expanded).people.length,11);
for (const missing of [['olga'],['jion','olga'],['jion']]) {
  assert.throws(()=>T.validate({...expanded,people:expanded.people.filter(p=>!missing.includes(p.id))}));
}
for (const person of ['vitoria','olga']) {
  const requestURL=new URL(T.requestURL(manualTasks[1],person,'assign'));
  const payload=JSON.parse(requestURL.searchParams.get('body').split('\n')[1]);
  assert.equal(payload.person,person);
  const active={...manualTasks[1],status:'active',assignee:person};
  const activePeople=expanded.people.map(p=>p.id===person?{...p,active:1,remaining_series:2}:p);
  assert.equal(T.validate({...expanded,people:activePeople,tasks:[manualTasks[0],active,manualTasks[2]]}).tasks[1].assignee,person);
  assert.throws(()=>T.validate({...manual,tasks:[manualTasks[0],active,manualTasks[2]]}));
  const legacyTask={...task,assignee:person};
  assert.throws(()=>T.validate({...snapshot,tasks:[legacyTask]}));
  assert.throws(()=>T.validate({...batched,tasks:batched.tasks.map(t=>({...t,lead:person}))}));
}
console.log('Eleven-person roster, request links and closed rollout compatibility passed');

for (const legacySnapshot of [snapshot,batched]) {
  const extra=['vitoria','olga'].map(id=>Object.fromEntries(Object.keys(legacySnapshot.people[0]).map(key=>[key,key==='id'?id:key==='name'?id:0])));
  const expandedLegacy={...legacySnapshot,people:[...legacySnapshot.people,...extra]};
  assert.equal(T.validate(expandedLegacy).people.length,11);
  assert.throws(()=>T.validate({...expandedLegacy,people:expandedLegacy.people.filter(p=>p.id!=='jion'&&p.id!=='olga')}));
}

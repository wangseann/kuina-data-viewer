'use strict';
const assert=require('node:assert/strict');
const K=require('../docs/explorer-core.js');
function record() {
  return {id:'synthetic',dataset:'synthetic-source',label:'Synthetic series',variable:'close',source:'Synthetic provider',nativeSeconds:900,price:true,role:'observations',decision:'ELIGIBLE',checks:['source_role','input_identity','series_type','numeric_observations','window_observations','value','timestamp','duplicate','source_parse','history_span','calendar','completeness','required_cadence','window_months','price_definition','hourly_coverage','longest_gap','ohlc'].map(id=>({id,status:'PASS'}))};
}
const good=record();assert.equal(K.eligible(good),true);
assert.equal(K.eligible({...good,checks:[]}),false);
assert.equal(K.eligible({...good,checks:[{id:'unrelated',status:'PASS'}]}),false,'A pass label cannot replace a full checklist');
assert.equal(K.eligible({...good,nativeSeconds:3600}),false);
assert.equal(K.eligible({...good,checks:[...good.checks,{id:'extra',status:'FAIL',reason:'availability_unverified'}]}),false);
const date='2025-04-01';
assert.equal(K.coverageState(good,null,date),'unknown');
assert.equal(K.coverageState({...good,historyStart:'2024-01-01',historyEnd:'2026-01-01'},null,date),'unknown','Endpoints do not certify interior coverage');
assert.equal(K.coverageState(good,{checked:true,observed:96,expected:96,longestGapSeconds:900},date),'complete');
assert.equal(K.coverageState(good,{checked:true,observed:95,expected:96,longestGapSeconds:null},date),'missing','A measured count shortfall stays visible without a gap length');
assert.equal(K.coverageState(good,{checked:true,observed:100,expected:96,longestGapSeconds:0},date),'unknown','Invalid counts must not turn green');
assert.equal(K.coverageState(good,{checked:true,observed:0,expected:0,longestGapSeconds:null},date),'closed');
assert.equal(K.coverageState({...good,nativeSeconds:3600},{checked:true,observed:24,expected:24,longestGapSeconds:3600},date),'coarse');
assert.equal(K.coverageState({...good,historyStart:'2025-05-01'},{checked:true,observed:0,expected:96,longestGapSeconds:86400},date),'outside');
const warning={...good,decision:'INELIGIBLE',checks:[{id:'gap',status:'FAIL',reason:'long_gaps'},{id:'span',status:'FAIL',reason:'short_history'},{id:'proof',status:'FAIL',reason:'availability_unverified'}]};
assert.equal(K.mask(warning),13);
assert.equal(K.matches(warning,'synthetic close','failed'),true);assert.equal(K.matches(warning,'synthetic','eligible'),false);assert.equal(K.matches(warning,'','4'),true);
const brief=K.repairBrief(warning,{auditUtc:'2026-11-09',windowStart:'2024-10-01',windowEnd:'2026-10-01'},{});
assert.equal(brief.acceptance.max_native_interval_seconds,900);assert.equal(brief.acceptance.minimum_calendar_years,2);assert.equal(brief.failures.length,3);assert.equal('enabled'in brief,false);
for(const path of ['/etc/passwd','../data','a/../b','https://example.com/data','a\\b'])assert.throws(()=>K.safePath(path));
assert.equal(K.dates('2024-10-01','2026-10-01').length,730);
console.log('Explorer checks passed: eligibility evidence, unknown coverage, calendar closures, overlapping failures, private paths and repair acceptance.');

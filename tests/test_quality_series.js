'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {webcrypto} = require('node:crypto');
if (!globalThis.crypto) Object.defineProperty(globalThis,'crypto',{value:webcrypto});
assert.ok(fs.existsSync(require('node:path').join(__dirname, '../docs/quality-series.js')), 'named hover loader must exist');
const quality = require('../docs/quality-series.js');
const ids = ['stocks','crypto','commodities','currencies','derivatives','economics','gdelt','prediction-markets','sentiment','emotions','trade','weather','reddit','other-markets'];
function fixture() {
  const summary = {schema:4,audit_utc:'2026-11-09T14:39:02+00:00',assessment_utc:'2026-11-10T01:00:00+00:00',types:ids.map(id => ({id,confirmed_series:0,excluded_series:0,failure_masks:[]}))};
  summary.types[0] = {...summary.types[0],confirmed_series:1,excluded_series:1,failure_masks:[{mask:3,count:1}]};
  const record = {id:'a'.repeat(64),label:'AAPL · Trade',variable:'close',source:'Exchange',native_seconds:60,mask:0};
  const index = {schema:1,audit_utc:summary.audit_utc,assessment_utc:summary.assessment_utc,counts_sha256:require('node:crypto').createHash('sha256').update(quality.canonicalJSON(summary)).digest('hex'),catalogue_sha256:'b'.repeat(64),types:ids.map(id => ({id,series:[]}))};
  index.types[0].series = [record,{...record,id:'c'.repeat(64),mask:3,native_seconds:3600}];
  const tile = mask => ({dataset:mask === 0 ? {} : {failureMask:String(mask)},attributes:{},setAttribute(key,value) { this.attributes[key] = value; }});
  const tiles = [tile(0),tile(3)];
  const grids = [0,1].map(i => ({dataset:{seriesType:'stocks',seriesState:i ? 'excluded':'eligible'},querySelectorAll:() => [tiles[i]]}));
  const status = {textContent:'',dataset:{countsSha256:index.counts_sha256,auditUtc:index.audit_utc,assessmentUtc:index.assessment_utc}};
  const document = {querySelectorAll:() => grids,getElementById:() => status};
  return {summary,index,tiles,grids,status,document};
}
(async () => {
  assert.deepEqual([...quality.visibleCounts([{mask:1,count:100000},{mask:15,count:1}])],[[1,3999],[15,1]]);
  const data = fixture();
  await quality.apply(data.document,data.index,data.summary);
  assert.match(data.tiles[0].attributes.title,/AAPL · Trade · close/);
  assert.match(data.tiles[0].attributes.title,/Eligible/);
  assert.match(data.tiles[1].attributes.title,/Missing data \/ gaps/);
  assert.match(data.tiles[1].attributes.title,/Coarser than 15 minutes/);
  assert.equal(data.tiles[0].attributes['aria-label'],data.tiles[0].attributes.title);
  for (const mutate of [
    d => d.index.counts_sha256 = 'd'.repeat(64),
    d => d.index.assessment_utc = '2026-11-11T00:00:00+00:00',
    d => d.index.types[0].series[0].label = '/datashare/private',
    d => d.index.types[0].series[0].variable = 'https://secret.example',
    d => d.index.types[0].series[0].source = 'bad\u0001',
    d => d.index.types[0].series[0].label = 'file=/datashare/private/name',
    d => d.index.types[0].series[0].label = 'file:///private/name',
    d => d.index.types[0].series[0].source = '/secret/another/path',
    d => d.index.types[0].series[0].values = [1],
    d => d.index.types[0].series[0].native_seconds = 0,
    d => d.index.types[0].series[1].id = d.index.types[0].series[0].id,
    d => d.index.types[0].series[1].mask = 2,
    d => d.grids[1].querySelectorAll = () => [],
    d => d.index.types.pop(),
    d => d.status.dataset.countsSha256 = 'e'.repeat(64),
    d => d.status.dataset.auditUtc = '2026-11-08T00:00:00+00:00',
  ]) {
    const bad = fixture(); mutate(bad);
    await assert.rejects(() => quality.apply(bad.document,bad.index,bad.summary));
    assert.deepEqual(bad.tiles.map(t => t.attributes),[{},{}], 'validation must precede all names');
  }
  const missing = fixture();
  await quality.load(missing.document, async () => { throw Error('offline'); });
  assert.match(missing.status.textContent,/unavailable/);
  assert.deepEqual(missing.tiles.map(t => t.attributes),[{},{}]);
  const oversized = fixture();
  let oversizedBodyRead = false;
  await quality.load(oversized.document,async () => ({ok:true,headers:{get:() => String(33*1024*1024)},text:async () => { oversizedBodyRead = true; throw Error('oversized body must not be read'); }}));
  assert.match(oversized.status.textContent,/unavailable/);
  assert.equal(oversizedBodyRead,false);
  const streamed = fixture();
  let cancelled = false;
  let reads = 0;
  await quality.load(streamed.document,async path => {
    if (path === 'summary.json') return {ok:true,headers:{get:() => null},text:async () => JSON.stringify(streamed.summary)};
    return {ok:true,headers:{get:() => null},body:{getReader:() => ({
      read:async () => { reads++; return {done:false,value:new Uint8Array(16*1024*1024+1)}; },
      cancel:async () => { cancelled = true; }
    })}};
  });
  assert.match(streamed.status.textContent,/unavailable/);
  assert.equal(reads,2);
  assert.equal(cancelled,true);
  assert.deepEqual(streamed.tiles.map(t => t.attributes),[{},{}]);
  console.log('quality series contract tests passed');
})().catch(error => { console.error(error); process.exitCode=1; });

/* Public names only: validate the complete snapshot before labelling any square. */
(function (root) {
  'use strict';
  const TYPES = ['stocks','crypto','commodities','currencies','derivatives','economics','gdelt','prediction-markets','sentiment','emotions','trade','weather','reddit','other-markets'];
  const HASH = /^[a-f0-9]{64}$/;
  const PRIVATE = /\/(?:datashare|flash|bucket|Users|home|private|mnt|scratch|tmp|var)\/|(?:^|[\s=,:;])\/[^\s/]*\/|[A-Za-z][A-Za-z0-9+.-]*:\/\/|[A-Za-z]:\\/i;
  const REASONS = [[1,'Missing data / gaps'],[2,'Coarser than 15 minutes'],[4,'Less than two years'],[8,'Other data issues / unfinished checks']];
  function keys(value, expected) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== expected.length || Object.keys(value).some(key => !expected.includes(key))) throw Error('Unexpected names metadata');
  }
  function text(value, maximum) {
    if (typeof value !== 'string' || !value.trim() || Array.from(value).length > maximum || /[\u0000-\u001f\u007f-\u009f]/.test(value) || PRIVATE.test(value)) throw Error('Unsafe public label');
  }
  function count(value) {
    if (!Number.isSafeInteger(value) || value < 0) throw Error('Invalid count');
  }
  function canonicalJSON(value) {
    if (Array.isArray(value)) return '[' + value.map(canonicalJSON).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonicalJSON(value[key])).join(',') + '}';
    return JSON.stringify(value);
  }
  function visibleCounts(buckets) {
    const counts = new Map();
    for (const bucket of buckets) {
      keys(bucket,['mask','count']);
      if (!Number.isInteger(bucket.mask) || bucket.mask < 1 || bucket.mask > 15 || counts.has(bucket.mask)) throw Error('Invalid failure combination');
      count(bucket.count);
      if (!bucket.count) throw Error('Empty failure combination');
      counts.set(bucket.mask,bucket.count);
    }
    const total = [...counts.values()].reduce((a,b) => a+b,0);
    if (!Number.isSafeInteger(total)) throw Error('Invalid total');
    if (total <= 4000) return counts;
    const remaining = 4000 - counts.size;
    const weight = total - counts.size;
    const result = new Map();
    const remainders = [];
    for (const [mask,n] of counts) {
      const product = remaining * (n-1);
      if (!Number.isSafeInteger(product)) throw Error('Invalid sampling count');
      result.set(mask,1 + Math.floor(product / weight));
      remainders.push({mask,remainder:product % weight});
    }
    remainders.sort((a,b) => b.remainder-a.remainder || a.mask-b.mask);
    const extra = 4000 - [...result.values()].reduce((a,b) => a+b,0);
    for (const {mask} of remainders.slice(0,extra)) result.set(mask,result.get(mask)+1);
    return result;
  }
  function summaryQuotas(summary) {
    if (summary?.schema !== 4 || !Array.isArray(summary.types) || summary.types.length !== TYPES.length) throw Error('Names need current counts');
    const quotas = new Map();
    for (const row of summary.types) {
      if (!TYPES.includes(row.id) || quotas.has(row.id) || !Array.isArray(row.failure_masks)) throw Error('Invalid counts categories');
      count(row.confirmed_series);
      count(row.excluded_series);
      const masks = visibleCounts(row.failure_masks);
      if (row.failure_masks.reduce((total,bucket) => total+bucket.count,0) !== row.excluded_series) throw Error('Invalid excluded total');
      masks.set(0,Math.min(row.confirmed_series,20000));
      quotas.set(row.id,masks);
    }
    return quotas;
  }
  async function validate(index, summary) {
    keys(index,['schema','audit_utc','assessment_utc','counts_sha256','catalogue_sha256','types']);
    if (index.schema !== 1 || typeof index.counts_sha256 !== 'string' || typeof index.catalogue_sha256 !== 'string' || !HASH.test(index.counts_sha256) || !HASH.test(index.catalogue_sha256)) throw Error('Invalid names snapshot');
    for (const field of ['audit_utc','assessment_utc']) {
      if (typeof index[field] !== 'string' || index[field] !== summary[field] || !Number.isFinite(Date.parse(index[field]))) throw Error('Stale names snapshot');
    }
    const digest = await root.crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonicalJSON(summary)));
    const actual = Array.from(new Uint8Array(digest),byte => byte.toString(16).padStart(2,'0')).join('');
    if (actual !== index.counts_sha256) throw Error('Counts do not match names');
    const quotas = summaryQuotas(summary);
    if (!Array.isArray(index.types) || index.types.length !== TYPES.length) throw Error('Invalid names categories');
    const types = new Set();
    const ids = new Set();
    for (const type of index.types) {
      keys(type,['id','series']);
      if (!quotas.has(type.id) || types.has(type.id) || !Array.isArray(type.series) || type.series.length > 24000) throw Error('Invalid names category');
      types.add(type.id);
      const remaining = new Map(quotas.get(type.id));
      let previous = 0;
      for (const record of type.series) {
        keys(record,['id','label','variable','source','native_seconds','mask']);
        if (typeof record.id !== 'string' || !HASH.test(record.id) || ids.has(record.id) || !Number.isInteger(record.mask) || record.mask < previous || record.mask > 15 || !(remaining.get(record.mask) > 0)) throw Error('Invalid named series or quota');
        ids.add(record.id);
        previous = record.mask;
        text(record.label,400);
        text(record.variable,128);
        text(record.source,128);
        if (record.native_seconds !== null && (typeof record.native_seconds !== 'number' || !Number.isFinite(record.native_seconds) || record.native_seconds <= 0 || record.native_seconds > Number.MAX_SAFE_INTEGER)) throw Error('Invalid native interval');
        remaining.set(record.mask,remaining.get(record.mask)-1);
      }
      if ([...remaining.values()].some(n => n !== 0)) throw Error('Missing named series');
    }
    return quotas;
  }
  function tooltip(record) {
    const interval = record.native_seconds === null ? 'Native interval unknown' : 'Native interval: ' + record.native_seconds + ' seconds';
    const decision = record.mask === 0 ? 'Eligible' : 'Excluded: ' + REASONS.filter(([bit]) => record.mask & bit).map(([,label]) => label).join('; ');
    return record.label + ' · ' + record.variable + '\nSource: ' + record.source + '\n' + interval + '\n' + decision;
  }
  async function apply(document, index, summary) {
    const quotas = await validate(index,summary);
    const page = document.getElementById('series-names-status')?.dataset;
    if (!page || page.countsSha256 !== index.counts_sha256 || page.auditUtc !== index.audit_utc || page.assessmentUtc !== index.assessment_utc) throw Error('Names differ from rendered page');
    const records = new Map(index.types.map(type => [type.id,type.series]));
    const seen = new Set();
    const changes = [];
    for (const grid of document.querySelectorAll('.series-grid')) {
      const {seriesType,seriesState} = grid.dataset;
      const key = seriesType + ':' + seriesState;
      if (!quotas.has(seriesType) || !['eligible','excluded'].includes(seriesState) || seen.has(key)) throw Error('Unexpected series grid');
      seen.add(key);
      const names = records.get(seriesType).filter(record => (record.mask === 0) === (seriesState === 'eligible'));
      const tiles = [...grid.querySelectorAll('.square')];
      if (tiles.length !== names.length) throw Error('Grid count differs from names');
      for (let i=0; i<tiles.length; i++) {
        const mask = seriesState === 'eligible' ? 0 : Number(tiles[i].dataset.failureMask);
        if (mask !== names[i].mask) throw Error('Grid failure differs from names');
        changes.push([tiles[i],tooltip(names[i])]);
      }
    }
    for (const [id,masks] of quotas) {
      if (masks.get(0) > 0 && !seen.has(id + ':eligible')) throw Error('Eligible grid missing');
      if ([...masks].some(([mask,n]) => mask > 0 && n > 0) && !seen.has(id + ':excluded')) throw Error('Excluded grid missing');
    }
    for (const [tile,label] of changes) {
      tile.setAttribute('title',label);
      tile.setAttribute('aria-label',label);
    }
    return changes.length;
  }
  async function fetchJSON(fetcher, path, limit) {
    const response = await fetcher(path,{cache:'no-store'});
    if (!response.ok || Number(response.headers.get('content-length')) > limit) throw Error('Names download unavailable or too large');
    if (!response.body?.getReader) {
      const body = await response.text();
      if (new TextEncoder().encode(body).length > limit) throw Error('Names download too large');
      return JSON.parse(body);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8',{fatal:true});
    let length = 0;
    let body = '';
    try {
      while (true) {
        const {value,done} = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > limit) throw Error('Names download too large');
        body += decoder.decode(value,{stream:true});
      }
      body += decoder.decode();
      return JSON.parse(body);
    } finally {
      await reader.cancel();
    }
  }
  async function load(document, fetcher) {
    const status = document.getElementById('series-names-status');
    try {
      const [summary,index] = await Promise.all([fetchJSON(fetcher,'summary.json',2*1024*1024),fetchJSON(fetcher,'series-names.json',32*1024*1024)]);
      const total = await apply(document,index,summary);
      if (status) status.textContent = 'Hover over a square for its series name, field and eligibility (' + total.toLocaleString() + ' shown).';
    } catch (_) {
      if (status) status.textContent = 'Series names unavailable or out of date. The counts and failure colours remain valid.';
    }
  }
  const api = {canonicalJSON,validate,apply,load,visibleCounts};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else if (root.document) load(root.document,root.fetch.bind(root));
})(globalThis);

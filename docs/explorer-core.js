/* Pure inspection rules. Reading a preview never changes an audit decision. */
(function (root) {
  'use strict';
  const DAY = 86400000;
  const COLOURS = {complete:'#25826b',missing:'#237cb6',coarse:'#e18c1f',outside:'#8654a8',unknown:'#7b8795',closed:'#ffffff'};
  const REASON_BITS = {no_valid_observations:1,no_window_data:1,missing_months:1,hourly_gaps:1,long_gaps:1,context_gaps:1,coarse_resolution:2,short_history:4};
  function safePath(value) {
    if (typeof value !== 'string' || !value || value.includes('\\') || value.startsWith('/') || value.split('/').some(part => !part || part === '.' || part === '..') || value.includes(':')) throw Error('Unsafe package path');
    return value;
  }
  function dates(start, end) {
    const first = Date.parse(start), last = Date.parse(end);
    if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first || (last-first) % DAY || last-first > 3660*DAY) throw Error('Invalid coverage window');
    return Array.from({length:(last-first)/DAY}, (_,index) => new Date(first+index*DAY).toISOString().slice(0,10));
  }
  function mask(record) {
    return (record.checks || []).filter(check => check.status === 'FAIL').reduce((value, check) => value | (REASON_BITS[check.reason] || 8), 0);
  }
  function eligible(record) {
    if (record.decision !== 'ELIGIBLE' || !Array.isArray(record.checks) || !Number.isFinite(record.nativeSeconds) || record.nativeSeconds <= 0 || record.nativeSeconds > 900 || typeof record.price !== 'boolean') return false;
    if (!record.checks.every(check => ['PASS','NOT_APPLICABLE'].includes(check.status))) return false;
    const required=['source_role','input_identity','series_type','numeric_observations','window_observations','value','timestamp','source_parse','history_span','calendar','completeness','required_cadence'];
    const events=['raw tweet events','raw event stream','scored tweet events'].includes(record.role);
    required.push(events?'forecast_aggregation':'duplicate');
    if (record.price) {
      required.push('window_months','price_definition','hourly_coverage','longest_gap');
      if (['open','high','low','close'].includes(String(record.variable).toLowerCase())) required.push('ohlc');
    } else {
      required.push('historical_availability');
      if (!events) required.push('context_periods');
    }
    if (['derived sentiment','raw tweet events','scored tweet events'].includes(record.role)) required.push('scrape_completeness');
    if (['derived sentiment','scored tweet events'].includes(record.role)) required.push('causal_processing');
    if (record.role==='scored tweet events') required.push('sentiment_score');
    const checks=new Map(record.checks.map(check=>[check.id,check.status]));
    return required.every(id=>checks.get(id)==='PASS'||(id==='calendar'&&events&&checks.get(id)==='NOT_APPLICABLE'));
  }
  function matches(record, term, filter) {
    const words = String(term).toLowerCase().trim().split(/\s+/).filter(Boolean);
    const text = [record.label,record.variable,record.source,record.units,JSON.stringify(record.entity || {})].join(' ').toLowerCase();
    if (!words.every(word => text.includes(word))) return false;
    if (filter === 'eligible') return eligible(record);
    if (filter === 'failed') return !eligible(record);
    if (filter !== 'all') return Boolean(mask(record) & Number(filter));
    return true;
  }
  function coverageState(record, cell, date) {
    if (!cell || cell.checked !== true) return 'unknown';
    if (cell.expected === 0) return 'closed';
    if (!Number.isInteger(cell.observed) || cell.observed < 0) return 'unknown';
    if (cell.observed === 0 && ((record.historyStart && date < record.historyStart.slice(0,10)) || (record.historyEnd && date > record.historyEnd.slice(0,10)))) return 'outside';
    if (Number.isFinite(record.nativeSeconds) && record.nativeSeconds > 900 && cell.observed > 0) return 'coarse';
    if (!Number.isInteger(cell.expected) || cell.expected < 1 || cell.observed > cell.expected) return 'unknown';
    if (cell.observed < cell.expected) return 'missing';
    if (!Number.isFinite(cell.longestGapSeconds) || cell.longestGapSeconds < 0) return 'unknown';
    if (cell.longestGapSeconds > 900) return 'missing';
    if (!(record.nativeSeconds > 0 && record.nativeSeconds <= 900)) return 'unknown';
    return 'complete';
  }
  function repairBrief(record, manifest, explanations) {
    const failed = (record.checks || []).filter(check => check.status === 'FAIL');
    return {
      kind:'kuina-repair-brief',version:1,series_id:record.id,dataset:record.datasetName||record.dataset,unit:record.label,variable:record.variable,entity:record.entity || {},source:record.source,source_group:record.sourceGroup||null,source_references:record.sourceReferences || [],source_reference_count:record.sourceReferenceCount||null,private_source_provenance:record.sourceProvenance||null,
      recorded_fields:{quote_side:record.quoteSide||null,construction:record.priceConstruction||null,adjustment:record.adjustment||null,units:record.units||null},
      audit_utc:manifest.auditUtc,assessment_utc:manifest.assessmentUtc || null,
      required_window:{start:manifest.windowStart,end_exclusive:manifest.windowEnd},
      acceptance:{minimum_calendar_years:2,max_native_interval_seconds:900,verify_internal_gaps:true,preserve_exact_instrument_source_venue_quote_and_units:true,rerun_all_eligibility_checks:true},
      failures:failed.map(check => ({check:check.id,reason:check.reason,meaning:(explanations[check.reason] || ['Other failed check','Inspect the saved audit evidence.'])[1],evidence:check.evidence ?? null})),
      instructions:['Check source availability and recording intervals before bulk collection.','Keep old data and prior releases. Do not fill gaps, copy values onto a finer grid, or substitute another instrument/venue/quote to claim a repair.','Collect or document the missing coverage, interval or evidence identified above.','Record source versions, retrieval dates, price meaning, calendar and historical publication details.','Report the result with provenance. Publish a new verified audit snapshot before changing the eligibility result.'],
      note:'Repair brief only. This file does not run collection, assign a participant or grant execution authority.'
    };
  }
  function validateManifest(data) {
    if (!data || data.schema !== 'kuina-inspection-v1' || !Array.isArray(data.datasets) || data.datasets.length > 100000) throw Error('This is not a supported inspection package');
    if (data.requirements?.maxNativeSeconds !== 900 || data.requirements?.minHistoryYears !== 2) throw Error('Package does not use the required 15-minute / two-year profile');
    dates(data.windowStart,data.windowEnd);
    const ids = new Set();
    for (const dataset of data.datasets) {
      if (typeof dataset.id !== 'string' || ids.has(dataset.id) || !Array.isArray(dataset.pages) || !Number.isSafeInteger(dataset.series) || dataset.series < 0) throw Error('Invalid dataset catalogue');
      ids.add(dataset.id);
      for (const page of dataset.pages) {
        safePath(page.path);
        if (!/^[a-f0-9]{64}$/.test(page.sha256) || !Number.isSafeInteger(page.bytes) || page.bytes < 1 || page.bytes > 32*1024*1024) throw Error('Invalid page identity');
      }
    }
    return data;
  }
  const api = {DAY,COLOURS,REASON_BITS,safePath,dates,mask,eligible,matches,coverageState,repairBrief,validateManifest};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KuinaInspection = api;
})(globalThis);

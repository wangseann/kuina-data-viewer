/* Public coordination metadata only. Claims are made in the private shared hub. */
(function (root) {
  'use strict';
  const TYPES = {stocks:'Stocks / ETFs',crypto:'Crypto',commodities:'Commodities',currencies:'Currencies',derivatives:'Derivatives',economics:'Economics',gdelt:'GDELT / news','prediction-markets':'Prediction markets',sentiment:'Tweets / Sentiments',emotions:'Emotions',trade:'Trade',weather:'Weather / rivers',reddit:'Reddit','other-markets':'Indices / bonds / other'};
  const PEOPLE = ['juan','emily','brian','amir','seann','taha','saswato','th','jion'];
  const STATUSES = {queued:'Ready to claim',active:'In progress',blocked:'Blocked — needs attention',awaiting_verification:'Work reported — audit pending',verified:'Verified complete'};
  const KINDS = {triage:'Inspect and plan',metadata:'Resolve metadata',preflight:'Check source feasibility',collection:'Collect missing data'};
  const REASONS = new Set(('inconsistent_ohlc ohlc_check_missing not_source_observations input_identity_unverified series_type_unknown no_valid_observations no_window_data invalid_values invalid_times conflicting_duplicates source_parse_error aggregation_unverified score_probability_invalid grid_alignment_invalid short_history calendar_unverified coarse_resolution cadence_unknown missing_months price_definition_unverified mixed_price_construction availability_unverified collection_completeness_unverified completeness_unverified hourly_gaps long_gaps context_gaps scrape_completeness causal_processing_unverified numeric_observations_check_missing window_observations_check_missing value_check_missing timestamp_check_missing duplicate_check_missing source_parse_check_missing sentiment_score_check_missing grid_alignment_check_missing history_span_check_missing window_months_check_missing').split(' '));
  function keys(value, allowed) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== allowed.length || Object.keys(value).some(key => !allowed.includes(key))) throw Error('Unexpected public task metadata');
  }
  function count(value) { if (!Number.isSafeInteger(value) || value < 0) throw Error('Invalid task count'); }
  function timestamp(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(value) || !Number.isFinite(Date.parse(value))) throw Error('Invalid task timestamp');
  }
  function validate(data) {
    keys(data,['schema_version','updated_at','profile','people','tasks']);
    if (data.schema_version !== 1) throw Error('Unsupported task board');
    timestamp(data.updated_at);
    keys(data.profile,['max_interval_seconds','min_years','unexplained_gaps_allowed']);
    if (data.profile.max_interval_seconds !== 900 || data.profile.min_years !== 2 || data.profile.unexplained_gaps_allowed !== 0) throw Error('Task board does not use our eligibility requirements');
    if (!Array.isArray(data.people) || data.people.length !== PEOPLE.length || !Array.isArray(data.tasks) || data.tasks.length > 50000) throw Error('Invalid task roster or size');
    const ids = new Set();
    for (const person of data.people) {
      keys(person,['id','name','queued','active','awaiting_verification','verified','load']);
      if (!PEOPLE.includes(person.id) || ids.has(person.id) || String(person.name).toLowerCase() !== person.id) throw Error('Unexpected participant');
      ids.add(person.id);
      for (const field of ['queued','active','awaiting_verification','verified','load']) count(person[field]);
    }
    ids.clear();
    for (const task of data.tasks) {
      keys(task,['id','category','kind','status','assignee','effort','affected_series','issues','created_at','updated_at']);
      if (!/^[a-zA-Z0-9_-]{1,96}$/.test(task.id) || ids.has(task.id) || !Object.hasOwn(TYPES,task.category) || !Object.hasOwn(KINDS,task.kind) || !Object.hasOwn(STATUSES,task.status) || !PEOPLE.includes(task.assignee)) throw Error('Unexpected task identity or status');
      ids.add(task.id);count(task.effort);count(task.affected_series);timestamp(task.created_at);timestamp(task.updated_at);
      if (!Array.isArray(task.issues) || task.issues.some(issue => !REASONS.has(issue))) throw Error('Unexpected task issue');
    }
    return data;
  }
  function matches(task, filters) { return ['person','category','status'].every(key => filters[key] === 'all' || task[key === 'person' ? 'assignee' : key] === filters[key]); }
  function stale(time, now=Date.now()) { return now - Date.parse(time) > 24*3600000; }
  const api = {TYPES,PEOPLE,STATUSES,KINDS,validate,matches,stale};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KuinaTasks = api;
})(globalThis);

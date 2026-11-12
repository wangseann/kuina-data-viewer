/* Public coordination metadata only. Claims are made in the private shared hub. */
(function (root) {
  'use strict';
  const TYPES = {stocks:'Stocks / ETFs',crypto:'Crypto',commodities:'Commodities',currencies:'Currencies',derivatives:'Derivatives',economics:'Economics',gdelt:'GDELT / news','prediction-markets':'Prediction markets',sentiment:'Tweets / Sentiments',emotions:'Emotions',trade:'Trade',weather:'Weather / rivers',reddit:'Reddit','other-markets':'Indices / bonds / other'};
  const PEOPLE = ['juan','emily','brian','amir','seann','taha','saswato','th','jion'];
  const STATUSES = {queued:'Ready to claim',active:'In progress',blocked:'Blocked — needs attention',awaiting_verification:'Work reported — audit pending',verified:'Verified complete',batched:'Divided into review batches'};
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
    const batched=data?.schema_version===2;
    keys(data,['schema_version','updated_at','profile','people','tasks',...(batched?['batch_limit']:[])]);
    if (![1,2].includes(data.schema_version)) throw Error('Unsupported task board');
    if(batched&&data.batch_limit!==500)throw Error('Invalid review batch limit');
    timestamp(data.updated_at);
    keys(data.profile,['max_interval_seconds','min_years','unexplained_gaps_allowed']);
    if (data.profile.max_interval_seconds !== 900 || data.profile.min_years !== 2 || data.profile.unexplained_gaps_allowed !== 0) throw Error('Task board does not use our eligibility requirements');
    if (!Array.isArray(data.people) || data.people.length !== PEOPLE.length || !Array.isArray(data.tasks) || data.tasks.length > 20000) throw Error('Invalid task roster or size');
    const ids = new Set();
    for (const person of data.people) {
      keys(person,['id','name','queued','active','awaiting_verification','verified','load',...(batched?['batched','remaining_series']:[])]);
      if (!PEOPLE.includes(person.id) || ids.has(person.id) || String(person.name).toLowerCase() !== person.id) throw Error('Unexpected participant');
      ids.add(person.id);
      for (const field of ['queued','active','awaiting_verification','verified','load',...(batched?['batched','remaining_series']:[])]) count(person[field]);
    }
    ids.clear();
    for (const task of data.tasks) {
      keys(task,['id','category','kind','status','assignee','effort','affected_series','issues','created_at','updated_at',...(batched?['lead','parent_id','batch_number','batch_total']:[])]);
      if (!/^[a-zA-Z0-9_-]{1,96}$/.test(task.id) || ids.has(task.id) || !Object.hasOwn(TYPES,task.category) || !Object.hasOwn(KINDS,task.kind) || !Object.hasOwn(STATUSES,task.status) || !PEOPLE.includes(task.assignee)) throw Error('Unexpected task identity or status');
      ids.add(task.id);count(task.effort);count(task.affected_series);timestamp(task.created_at);timestamp(task.updated_at);
      if (!Array.isArray(task.issues) || task.issues.some(issue => !REASONS.has(issue))) throw Error('Unexpected task issue');
    }
    if(batched)validateBatches(data);
    return data;
  }
  function validateBatches(data) {
    const tasks=new Map(data.tasks.map(task=>[task.id,task])),children=new Map();
    const totals=new Map(PEOPLE.map(id=>[id,{queued:0,active:0,awaiting_verification:0,verified:0,load:0,batched:0,remaining_series:0}]));
    for(const task of data.tasks) {
      if(!PEOPLE.includes(task.lead))throw Error('Unexpected dataset lead');
      count(task.batch_number);count(task.batch_total);
      if(task.parent_id!==null) {
        const parent=tasks.get(task.parent_id);
        if(!parent||parent.status!=='batched'||parent.parent_id!==null||parent.category!==task.category||task.lead!==parent.assignee||task.batch_total!==parent.batch_total||task.batch_number<1||task.batch_number>task.batch_total||task.kind!=='triage'||task.affected_series<1||task.affected_series>500)throw Error('Invalid review partition');
        if(!children.has(parent.id))children.set(parent.id,new Set());
        const numbers=children.get(parent.id);
        if(numbers.has(task.batch_number))throw Error('Duplicate review batch');
        numbers.add(task.batch_number);
      } else if(task.batch_number!==0||(task.status!=='batched'&&task.batch_total!==0))throw Error('Unexpected batch numbering');
      const total=totals.get(task.assignee);
      total[task.status==='blocked'?'active':task.status]++;
      if(!['batched','verified'].includes(task.status)) {
        total.load+=task.effort;
        if(task.kind==='triage')total.remaining_series+=task.affected_series;
      }
    }
    for(const task of data.tasks)if(task.status==='batched'&&(task.kind!=='triage'||task.parent_id!==null||task.lead!==task.assignee||task.batch_total<1||children.get(task.id)?.size!==task.batch_total))throw Error('Incomplete dataset batch plan');
    for(const person of data.people)for(const [key,value]of Object.entries(totals.get(person.id)))if(person[key]!==value)throw Error('Team workload does not match the queue');
  }
  function remaining(person,data) {
    if(data.schema_version===2)return person.remaining_series;
    return data.tasks.filter(task=>task.assignee===person.id&&task.kind==='triage'&&task.status!=='verified').reduce((sum,task)=>sum+task.affected_series,0);
  }
  function reviewTasks(data,filters) {
    return data.tasks.filter(task=>(filters.status==='batched'||task.status!=='batched')&&matches(task,filters));
  }
  function page(tasks,index,size=40) {
    const pages=Math.max(1,Math.ceil(tasks.length/size));
    const selected=Math.max(0,Math.min(Number.isInteger(index)?index:0,pages-1));
    return {index:selected,pages,rows:tasks.slice(selected*size,(selected+1)*size),start:tasks.length?selected*size+1:0,end:Math.min((selected+1)*size,tasks.length),total:tasks.length};
  }
  function rollups(data) {
    return data.tasks.filter(task=>task.kind==='triage'&&!task.parent_id).map(parent=>{
      const batches=data.tasks.filter(task=>task.parent_id===parent.id);
      const leaves=batches.length?batches:[parent];
      return {category:parent.category,lead:parent.lead||parent.assignee,batches:batches.length,verified:batches.filter(task=>task.status==='verified').length,records:leaves.reduce((sum,task)=>sum+task.affected_series,0),remaining:leaves.filter(task=>task.status!=='verified').reduce((sum,task)=>sum+task.affected_series,0)};
    }).sort((a,b)=>TYPES[a.category].localeCompare(TYPES[b.category]));
  }
  function matches(task, filters) { return ['person','category','status'].every(key => filters[key] === 'all' || task[key === 'person' ? 'assignee' : key] === filters[key]); }
  function stale(time, now=Date.now()) { return now - Date.parse(time) > 24*3600000; }
  const api = {TYPES,PEOPLE,STATUSES,KINDS,validate,matches,stale,remaining,reviewTasks,page,rollups};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KuinaTasks = api;
})(globalThis);

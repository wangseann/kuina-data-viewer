/* Closed public metadata schema and safe GitHub request links. */
(function (root) {
  'use strict';
  const TYPES = {stocks:'Stocks / ETFs',crypto:'Crypto',commodities:'Commodities',currencies:'Currencies',derivatives:'Derivatives',economics:'Economics',gdelt:'GDELT / news','prediction-markets':'Prediction markets',sentiment:'Tweets / Sentiments',emotions:'Emotions',trade:'Trade',weather:'Weather / rivers',reddit:'Reddit','other-markets':'Indices / bonds / other'};
  const PEOPLE = ['juan','emily','brian','amir','seann','taha','saswato','th','jion','vitoria','olga'];
  const LEGACY_PEOPLE = ['juan','emily','brian','amir','seann','taha','saswato','th','jion'];
  const STATUSES = {available:'Available',assigned:'Assigned · ready for agent',active:'In progress',blocked:'Blocked',awaiting_verification:'Work reported · review pending',verified:'Verified complete',batched:'Divided into review batches',queued:'Legacy assignment'};
  const KINDS = {triage:'Inspect and plan',metadata:'Resolve metadata',preflight:'Check source feasibility',collection:'Collect missing data'};
  const REASONS = new Set(('inconsistent_ohlc ohlc_check_missing not_source_observations input_identity_unverified series_type_unknown no_valid_observations no_window_data invalid_values invalid_times conflicting_duplicates source_parse_error aggregation_unverified score_probability_invalid grid_alignment_invalid short_history calendar_unverified coarse_resolution cadence_unknown missing_months price_definition_unverified mixed_price_construction availability_unverified collection_completeness_unverified completeness_unverified hourly_gaps long_gaps context_gaps scrape_completeness causal_processing_unverified numeric_observations_check_missing window_observations_check_missing value_check_missing timestamp_check_missing duplicate_check_missing source_parse_check_missing sentiment_score_check_missing grid_alignment_check_missing history_span_check_missing window_months_check_missing').split(' '));
  const ID = /^[a-zA-Z0-9_-]{1,96}$/;
  function keys(value, allowed) {
    if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== allowed.length || Object.keys(value).some(key => !allowed.includes(key))) throw Error('Unexpected public task metadata');
  }
  function count(value, maximum=Number.MAX_SAFE_INTEGER) {
    if (!Number.isSafeInteger(value) || value < 0 || value > maximum) throw Error('Invalid task count');
  }
  function timestamp(value) {
    if (typeof value !== 'string' || value.length > 40 || !/^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(value) || !Number.isFinite(Date.parse(value))) throw Error('Invalid task timestamp');
  }
  function validate(data) {
    const manual = data?.schema_version === 3;
    const batched = manual || data?.schema_version === 2;
    keys(data,['schema_version','updated_at','profile','people','tasks',...(batched?['batch_limit']:[])]);
    if (![1,2,3].includes(data.schema_version)) throw Error('Unsupported task board');
    if (batched && data.batch_limit !== 500) throw Error('Invalid review batch limit');
    if (JSON.stringify(data).length > 16*1024*1024) throw Error('Task snapshot is too large');
    timestamp(data.updated_at);
    keys(data.profile,['max_interval_seconds','min_years','unexplained_gaps_allowed']);
    if (data.profile.max_interval_seconds !== 900 || data.profile.min_years !== 2 || data.profile.unexplained_gaps_allowed !== 0) throw Error('Task board does not use our eligibility requirements');
    if (!Array.isArray(data.people) || ![LEGACY_PEOPLE.length,PEOPLE.length].includes(data.people.length) || !Array.isArray(data.tasks) || data.tasks.length > (batched?20000:10000)) throw Error('Invalid task roster or size');
    const personCounts = manual ? ['assigned','active','awaiting_verification','verified','remaining_series'] : ['queued','active','awaiting_verification','verified','load',...(batched?['batched','remaining_series']:[])];
    const ids = new Set();
    for (const person of data.people) {
      keys(person,['id','name',...personCounts]);
      if (!PEOPLE.includes(person.id) || ids.has(person.id) || typeof person.name !== 'string' || person.name.toLowerCase() !== person.id) throw Error('Unexpected participant');
      ids.add(person.id);
      for (const field of personCounts) count(person[field]);
    }
    const roster = new Set(ids);
    if (![LEGACY_PEOPLE,PEOPLE].some(people=>people.length === roster.size && people.every(id=>roster.has(id)))) throw Error('Invalid task roster');
    ids.clear();
    for (const task of data.tasks) {
      const extras = manual ? ['parent_id','batch_number','batch_total','assignment_issue'] : ['effort',...(batched?['lead','parent_id','batch_number','batch_total']:[])];
      keys(task,['id','category','kind','status','assignee','affected_series','issues','created_at','updated_at',...extras]);
      const statuses = manual ? ['available','assigned','active','blocked','awaiting_verification','verified','batched'] : ['queued','active','blocked','awaiting_verification','verified',...(batched?['batched']:[])];
      if (typeof task.id !== 'string' || !ID.test(task.id) || ids.has(task.id) || !Object.hasOwn(TYPES,task.category) || !Object.hasOwn(KINDS,task.kind) || !statuses.includes(task.status)) throw Error('Unexpected task identity or status');
      ids.add(task.id);
      count(task.affected_series);
      timestamp(task.created_at);
      timestamp(task.updated_at);
      if (!Array.isArray(task.issues) || task.issues.some(issue => !REASONS.has(issue)) || new Set(task.issues).size !== task.issues.length) throw Error('Unexpected task issue');
      if (manual) {
        const unassigned = ['available','batched'].includes(task.status);
        if (unassigned ? task.assignee !== null : !roster.has(task.assignee)) throw Error('Invalid task assignment');
        if (task.assignment_issue !== null) {
          count(task.assignment_issue);
          if (!task.assignment_issue || unassigned) throw Error('Invalid assignment issue');
        }
      } else {
        if (!roster.has(task.assignee)) throw Error('Unexpected participant');
        count(task.effort,100);
        if (!task.effort) throw Error('Invalid legacy effort');
      }
    }
    if (batched) validateBatches(data,manual,personCounts,roster);
    return data;
  }
  function validateBatches(data,manual,personCounts,roster) {
    const tasks = new Map(data.tasks.map(task=>[task.id,task]));
    const children = new Map();
    const totals = new Map([...roster].map(id=>[id,Object.fromEntries(personCounts.map(key=>[key,0]))]));
    for (const task of data.tasks) {
      if (!manual && !roster.has(task.lead)) throw Error('Unexpected legacy category owner');
      count(task.batch_number,20000);
      count(task.batch_total,20000);
      if (task.parent_id !== null) {
        const parent = tasks.get(task.parent_id);
        if (typeof task.parent_id !== 'string' || !ID.test(task.parent_id) || !parent || parent.status !== 'batched' || parent.parent_id !== null || parent.category !== task.category || task.batch_total !== parent.batch_total || task.batch_number < 1 || task.batch_number > task.batch_total || task.kind !== 'triage' || task.status === 'batched' || task.affected_series < 1 || task.affected_series > 500) throw Error('Invalid review partition');
        if (!manual && (task.lead !== parent.assignee || task.effort !== Math.min(5,Math.ceil(task.affected_series/100)))) throw Error('Invalid legacy review partition');
        if (!children.has(parent.id)) children.set(parent.id,new Set());
        const numbers = children.get(parent.id);
        if (numbers.has(task.batch_number)) throw Error('Duplicate review batch');
        numbers.add(task.batch_number);
      } else if (task.batch_number !== 0 || ((task.status === 'batched') !== (task.batch_total > 0))) throw Error('Unexpected batch numbering');
      if (task.assignee !== null) {
        const total = totals.get(task.assignee);
        total[task.status === 'blocked' ? 'active' : task.status]++;
        if (!['batched','verified'].includes(task.status)) {
          if (!manual) total.load += task.effort;
          if (task.kind === 'triage') total.remaining_series += task.affected_series;
        }
      }
    }
    for (const task of data.tasks) {
      if (task.status === 'batched' && (task.kind !== 'triage' || task.parent_id !== null || (!manual && task.lead !== task.assignee) || children.get(task.id)?.size !== task.batch_total)) throw Error('Incomplete dataset batch plan');
    }
    for (const person of data.people) {
      for (const [key,value] of Object.entries(totals.get(person.id))) {
        if (person[key] !== value) throw Error('Team totals do not match the queue');
      }
    }
  }
  function remaining(person,data) {
    if (data.schema_version >= 2) return person.remaining_series;
    return data.tasks.filter(task=>task.assignee===person.id&&task.kind==='triage'&&task.status!=='verified').reduce((sum,task)=>sum+task.affected_series,0);
  }
  function reviewTasks(data,filters) {
    return data.tasks.filter(task=>(filters.status==='batched'||task.status!=='batched')&&matches(task,filters));
  }
  function page(tasks,index,size=40) {
    const pages = Math.max(1,Math.ceil(tasks.length/size));
    const selected = Math.max(0,Math.min(Number.isInteger(index)?index:0,pages-1));
    return {index:selected,pages,rows:tasks.slice(selected*size,(selected+1)*size),start:tasks.length?selected*size+1:0,end:Math.min((selected+1)*size,tasks.length),total:tasks.length};
  }
  function availableRecords(data) {
    return data.tasks.filter(task=>task.kind==='triage'&&task.status==='available').reduce((sum,task)=>sum+task.affected_series,0);
  }
  function rollups(data) {
    const children = new Map();
    for (const task of data.tasks) {
      if (!task.parent_id) continue;
      if (!children.has(task.parent_id)) children.set(task.parent_id,[]);
      children.get(task.parent_id).push(task);
    }
    return data.tasks.filter(task=>task.kind==='triage'&&!task.parent_id).map(parent=>{
      const batches = children.get(parent.id) || [];
      const leaves = batches.length ? batches : [parent];
      const available = leaves.filter(task=>task.status==='available');
      return {category:parent.category,batches:batches.length,verified:batches.filter(task=>task.status==='verified').length,available:available.length,available_records:available.reduce((sum,task)=>sum+task.affected_series,0),records:leaves.reduce((sum,task)=>sum+task.affected_series,0),remaining:leaves.filter(task=>task.status!=='verified').reduce((sum,task)=>sum+task.affected_series,0)};
    }).sort((a,b)=>TYPES[a.category].localeCompare(TYPES[b.category]));
  }
  function requestURL(task,person,action) {
    if (!task || typeof task.id !== 'string' || !ID.test(task.id) || !PEOPLE.includes(person) || !['assign','release'].includes(action)) throw Error('Choose a valid person and task');
    if (action === 'assign' && (task.status !== 'available' || task.assignee !== null)) throw Error('Only available work can be requested');
    if (action === 'release' && (task.status !== 'assigned' || task.assignee !== person)) throw Error('Only your unstarted assignment can be released');
    const request = {version:1,action,task_id:task.id,person};
    if (action === 'release') {
      count(task.assignment_issue);
      if (!task.assignment_issue) throw Error('Assignment issue required for release');
      request.assignment_issue = task.assignment_issue;
    }
    const url = new URL('https://github.com/wangseann/kuina-data-viewer/issues/new');
    url.searchParams.set('title','[Kuina '+(action==='assign'?'claim':'release')+'] '+task.id);
    url.searchParams.set('body','<!-- kuina-request-v1\n'+JSON.stringify(request)+'\n-->');
    return url.href;
  }
  function matches(task,filters) {
    return ['person','category','status'].every(key=>filters[key]==='all'||task[key==='person'?'assignee':key]===filters[key]);
  }
  function stale(time,now=Date.now()) { return now-Date.parse(time)>24*3600000; }
  const api = {TYPES,PEOPLE,STATUSES,KINDS,validate,matches,stale,remaining,reviewTasks,page,rollups,availableRecords,requestURL};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KuinaTasks = api;
})(globalThis);

"""Build one static unique-work dashboard from closed reviewed public metadata.

No audit, claim backend, publishing, observations, or private target information.
"""
import base64
import recovery
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

SUMMARY_SCHEMA = 'kuina-unique-public-summary-v1'
ELIGIBILITY_SUMMARY_SCHEMA = 'kuina-unique-public-summary-v2'
TASK_SCHEMA = 'kuina-unique-public-tasks-v1'
PEOPLE = dict(juan='Juan',emily='Emily',brian='Brian',amir='Amir',seann='Seann',taha='Taha',saswato='Saswato',th='TH',jion='Jion',vitoria='Vitoria',olga='Olga')
CATEGORIES = dict(stocks='Stocks / ETFs',crypto='Crypto',commodities='Commodities',currencies='Currencies',derivatives='Derivatives',economics='Economics',gdelt='GDELT / news',sentiment='Tweets / Sentiments',emotions='Emotions',trade='Trade',weather='Weather / rivers',reddit='Reddit',**{'prediction-markets':'Prediction markets','other-markets':'Indices / bonds / other'})
STATUSES = dict(available='Available',assigned='Assigned',active='In progress',blocked='Blocked',awaiting_verification='Awaiting verification',verified='Verified work')
BLOCKERS = frozenset('gaps resolution history meaning timing source_unavailable identity_review legacy_reservation unverified'.split())
COUNT_FIELDS = ('stored_numeric_series','unique_work_targets','distinct_measurement_groups','targets_with_saved_eligible_fields','unresolved_identity_targets')


def require(condition,message):
    if not condition:
        raise ValueError(message)


def keys(value,expected):
    require(type(value) is dict and set(value)==set(expected),'Unexpected public metadata fields')


def count(value):
    require(type(value) is int and 0<=value<=9007199254740991,'Invalid public count')


def timestamp(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[.]\d{1,6})?Z',value) is not None,'UTC generation timestamp required')
    datetime.fromisoformat(value[:-1]+'+00:00')


def validate(summary,tasks):
    summary_fields = ('schema','generated_at','input_manifest_sha256','grouping_status','categories')
    require(type(summary) is dict, 'Unique summary must be an object')
    if summary.get('schema') == ELIGIBILITY_SUMMARY_SCHEMA:
        keys(summary, (*summary_fields, 'eligibility'))
        evidence = summary['eligibility']
        keys(evidence, ('assessed_at', 'quality_manifest_sha256', 'proof_sha256'))
        timestamp(evidence['assessed_at'])
        for field in ('quality_manifest_sha256', 'proof_sha256'):
            require(type(evidence[field]) is str and re.fullmatch('[0-9a-f]{64}', evidence[field]) is not None,
                    'Eligibility evidence SHA256 required')
    else:
        keys(summary, summary_fields)
    keys(tasks,('schema','generated_at','people','batches'))
    require(summary['schema'] in (SUMMARY_SCHEMA, ELIGIBILITY_SUMMARY_SCHEMA) and tasks['schema']==TASK_SCHEMA,'Unsupported unique dashboard metadata')
    timestamp(summary['generated_at']);timestamp(tasks['generated_at'])
    if summary['schema'] == ELIGIBILITY_SUMMARY_SCHEMA:
        require(datetime.fromisoformat(summary['eligibility']['assessed_at'].replace('Z', '+00:00')) >=
                datetime.fromisoformat(summary['generated_at'].replace('Z', '+00:00')),
                'Eligibility assessment cannot predate the grouping snapshot')
    require(type(summary['input_manifest_sha256']) is str and re.fullmatch('[0-9a-f]{64}',summary['input_manifest_sha256']) is not None,'Manifest SHA256 required')
    require(summary['grouping_status'] in ('VERIFIED_WITHIN_DATASETS','VERIFIED_CROSS_SOURCE'),'Reviewed verified grouping status required')
    require(type(summary['categories']) is list and 0<len(summary['categories'])<=len(CATEGORIES),'Invalid category list')
    categories={}
    for category in summary['categories']:
        keys(category,('id',*COUNT_FIELDS))
        require(type(category['id']) is str and category['id'] in CATEGORIES and category['id'] not in categories,'Unknown or repeated category')
        for field in COUNT_FIELDS:count(category[field])
        require(category['unique_work_targets']<=category['distinct_measurement_groups']<=category['stored_numeric_series'],'Inconsistent series, measurement and work counts')
        require(category['targets_with_saved_eligible_fields']<=category['unique_work_targets'] and category['unresolved_identity_targets']<=category['unique_work_targets'],'Inconsistent target counts')
        categories[category['id']]=category
    require(type(tasks['people']) is list and len(tasks['people'])==len(PEOPLE),'All eleven participants required')
    roster={}
    for person in tasks['people']:
        keys(person,('id','name'))
        require(type(person['id']) is str and person['id'] in PEOPLE and person['name']==PEOPLE[person['id']] and person['id'] not in roster,'Unexpected participant identity')
        roster[person['id']]=person['name']
    require(type(tasks['batches']) is list and len(tasks['batches'])<=20000,'At most20000 public batches allowed')
    seen=set();scope={key:[0,0] for key in categories}
    for batch in tasks['batches']:
        keys(batch,('id','category','target_count','series_count','status','assignee','assignment_issue','blocker_codes'))
        require(type(batch['id']) is str and re.fullmatch('[A-Za-z0-9_-]{1,96}',batch['id']) is not None and batch['id'] not in seen,'Invalid or repeated public batch ID')
        seen.add(batch['id'])
        require(type(batch['category']) is str and type(batch['status']) is str and batch['category'] in categories and batch['status'] in STATUSES,'Unexpected batch category/status')
        count(batch['target_count']);count(batch['series_count'])
        require(0<batch['target_count']<=batch['series_count'],'Invalid batch scope')
        require(batch['assignee'] is None or (type(batch['assignee']) is str and batch['assignee'] in roster),'Unexpected assignee')
        require(batch['status']!='available' or (batch['assignee'] is None and batch['assignment_issue'] is None),'Available batches cannot have assignments')
        require(batch['status'] not in ('assigned','active') or batch['assignee'] in roster,'Assigned and active work needs a participant')
        if batch['assignment_issue'] is not None:
            count(batch['assignment_issue'])
            require(batch['assignment_issue']>0 and batch['assignee'] in roster,'Invalid GitHub assignment issue')
        blockers=batch['blocker_codes']
        require(type(blockers) is list and len(blockers)<=len(BLOCKERS) and all(type(code) is str and code in BLOCKERS for code in blockers) and len(set(blockers))==len(blockers),'Unexpected blocker codes')
        scope[batch['category']][0]+=batch['target_count'];scope[batch['category']][1]+=batch['series_count']
    for category,(targets,series) in scope.items():
        require(targets<=categories[category]['unique_work_targets'] and series<=categories[category]['stored_numeric_series'],'Batch scope exceeds reviewed category counts')
    require(len(json.dumps(summary,allow_nan=False).encode())<=64*1024 and len(json.dumps(tasks,allow_nan=False).encode())<=8*1024**2,'Public metadata byte bound exceeded')
    return True


def require_current_eligibility(previous, incoming):
    """Reject stale eligibility metadata after both summaries have been validated."""
    if previous['schema'] == ELIGIBILITY_SUMMARY_SCHEMA:
        require(incoming['schema'] == ELIGIBILITY_SUMMARY_SCHEMA,
                'Current eligibility counts cannot revert to a saved grouping snapshot')
        old = datetime.fromisoformat(previous['eligibility']['assessed_at'].replace('Z', '+00:00'))
        new = datetime.fromisoformat(incoming['eligibility']['assessed_at'].replace('Z', '+00:00'))
        require(new >= old, 'Older eligibility assessment cannot replace current counts')


def require_active_batches(tasks):
    """Historical snapshots remain readable; excluded batches cannot republish."""
    require(not any(recovery.retired_batch(row['id']) for row in tasks['batches']),
            'Confirmed unrecoverable batches cannot enter an active work snapshot')


CORE_SCRIPT = r"""const KuinaUnique = (() => {
  const PEOPLE = new Set(['juan','emily','brian','amir','seann','taha','saswato','th','jion','vitoria','olga']);
  const CATEGORIES = new Set(['stocks','crypto','commodities','currencies','derivatives','economics','gdelt','prediction-markets','sentiment','emotions','trade','weather','reddit','other-markets']);
  const FINANCIAL = new Set(['stocks','crypto','commodities','currencies','derivatives','other-markets']);
  function claimable(batch) {
    return batch.status==='available' && batch.assignee===null && batch.assignment_issue===null && Array.isArray(batch.blocker_codes) && batch.blocker_codes.length===0;
  }
  function requestURL(batch,person) {
    if (!batch || typeof batch.id!=='string' || !/^[A-Za-z0-9_-]{1,96}$/.test(batch.id) || !PEOPLE.has(person) || !claimable(batch)) throw Error('Choose an available, unblocked batch and a participant');
    const url=new URL('https://github.com/wangseann/kuina-data-viewer/issues/new');
    url.searchParams.set('title','[Kuina claim] '+batch.id);
    url.searchParams.set('body','<!-- kuina-request-v1\n'+JSON.stringify({version:1,action:'assign',task_id:batch.id,person})+'\n-->');
    return url.href;
  }
  function workerCommand(batch,person) {
    if (!batch || typeof batch!=='object' || Array.isArray(batch) || !PEOPLE.has(person) || batch.assignee!==person) return null;
    if (typeof batch.id!=='string' || batch.id.length<1 || batch.id.length>96 || /[^A-Za-z0-9_-]/.test(batch.id)) return null;
    const confirmed=Number.isSafeInteger(batch.assignment_issue) && batch.assignment_issue>0;
    const prefix='python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" ';
    if (batch.status==='assigned' && confirmed) return prefix+"prepare-work '"+batch.id+"' --person '"+person+"' --assignment-issue "+batch.assignment_issue;
    if (['active','blocked','awaiting_verification'].includes(batch.status) && (batch.assignment_issue===null || confirmed)) return prefix+"show '"+batch.id+"'";
    return null;
  }
  function reviewKind(batch) {
    if (!batch || typeof batch!=='object' || Array.isArray(batch) || !CATEGORIES.has(batch.category)) return 'unknown';
    if (typeof batch.id!=='string' || batch.id.length>96 || /[^A-Za-z0-9_-]/.test(batch.id)) return 'unknown';
    const prefix='unique-'+batch.category+'-';
    if (!batch.id.startsWith(prefix)) return 'unknown';
    const match=/^(prices|series|fao|psd|cftc|comtrade|equities|fx|wide|identity|mixed-prices|ports|geo|accounts|cross-source)-(review|statistical|identity)-[0-9a-f]{16}-[0-9]{6}$/.exec(batch.id.slice(prefix.length));
    if (!match) return 'unknown';
    const [,mode,planning]=match;
    if (planning==='statistical') return 'statistical';
    if (planning==='identity') return 'identity';
    if (['prices','equities','fx','mixed-prices'].includes(mode) || (mode==='cross-source' && FINANCIAL.has(batch.category))) return 'market';
    return 'context';
  }
  function matches(batch,filters) {
    return ['category','status','person'].every(key=>filters[key]==='all'||batch[key==='person'?'assignee':key]===filters[key]) &&
      (filters.kind===undefined || filters.kind==='all' || reviewKind(batch)===filters.kind);
  }
  return {claimable,requestURL,workerCommand,reviewKind,matches};
})();"""

SCRIPT = r"""
(() => {
  'use strict';
  const data=JSON.parse(document.getElementById('unique-data').textContent);
  const names=new Map(data.tasks.people.map(p=>[p.id,p.name]));
  const labels=data.category_labels, statuses=data.status_labels;
  const el=id=>document.getElementById(id), format=n=>n.toLocaleString();
  const pending=new Set(); let page=0; const pageSize=50;
  function node(tag,text) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  function option(select,value,text) {const o=node('option',text);o.value=value;select.append(o);}
  data.tasks.people.forEach(p=>{option(el('identity'),p.id,p.name);option(el('person'),p.id,p.name);});
  data.summary.categories.forEach(c=>option(el('category'),c.id,labels[c.id]));
  Object.entries(statuses).forEach(([id,label])=>option(el('status'),id,label));
  for(const c of data.summary.categories) {
    const row=node('tr'); row.append(node('th',labels[c.id]));
    for(const key of ['stored_numeric_series','unique_work_targets','distinct_measurement_groups','targets_with_saved_eligible_fields','unresolved_identity_targets'])row.append(node('td',format(c[key])));
    el('counts').append(row);
  }
  function render() {
    const filters={category:el('category').value,status:el('status').value,person:el('person').value,kind:el('review-kind').value};
    const batches=data.tasks.batches.filter(b=>KuinaUnique.matches(b,filters));
    const pages=Math.max(1,Math.ceil(batches.length/pageSize));page=Math.min(page,pages-1);
    el('queue').replaceChildren();el('visible-count').textContent=format(batches.length)+' matching batches';
    el('page').textContent='Page '+(page+1)+' / '+pages;
    el('previous').disabled=page===0;el('next').disabled=page+1>=pages;
    for(const batch of batches.slice(page*pageSize,(page+1)*pageSize)) {
      const row=node('tr'), id=node('td',batch.id);id.append(node('small',labels[batch.category]));
      const person=node('td',batch.assignee?names.get(batch.assignee):'Unassigned');
      if(batch.assignment_issue){const link=node('a','Issue #'+batch.assignment_issue);link.href='https://github.com/wangseann/kuina-data-viewer/issues/'+batch.assignment_issue;link.target='_blank';link.rel='noopener noreferrer';person.append(node('br'),link);}
      const action=node('td');
      const command=KuinaUnique.workerCommand(batch,el('identity').value);
      if(command){
        const button=node('button','Agent command');button.type='button';
        const help=node('small'),pre=node('pre'),code=node('code');pre.hidden=true;pre.append(code);
        button.addEventListener('click',()=>{
          code.textContent=command;pre.hidden=false;
          help.textContent=batch.status==='assigned'?'Run this in your agent’s private environment. Submit the returned GitHub start request, wait for confirmation, then let the same agent claim its preparation hash.':'Inspect the current private state before continuing. This command does not create another worker claim.';
        });action.append(button,help,pre);
      }
      else if(pending.has(batch.id))action.append(node('span','Request opened · pending sync'));
      else if(KuinaUnique.claimable(batch)&&el('identity').value){
        const link=node('a','Claim via GitHub');link.href=KuinaUnique.requestURL(batch,el('identity').value);link.target='_blank';link.rel='noopener noreferrer';
        link.addEventListener('click',()=>{pending.add(batch.id);el('request-note').textContent='GitHub opened for '+batch.id+'. Submit the prepared issue there. Pending until the confirmed snapshot is refreshed; opening a request does not assign or start work.';render();});action.append(link);
      } else action.append(node('span',KuinaUnique.claimable(batch)?'Choose “I am” above':'No claim available'));
      row.append(id,node('td',format(batch.target_count)),node('td',format(batch.series_count)),node('td',statuses[batch.status]),person,node('td',batch.blocker_codes.length?batch.blocker_codes.join(' · ').replaceAll('_',' '):'None recorded'),action);
      el('queue').append(row);
    }
    if(!batches.length){const row=node('tr'),cell=node('td','No batches match these filters.');cell.colSpan=7;row.append(cell);el('queue').append(row);}
  }
  for(const id of ['category','review-kind','status','person','identity'])el(id).addEventListener('change',()=>{page=0;render();});
  el('previous').addEventListener('click',()=>{page--;render();});el('next').addEventListener('click',()=>{page++;render();});
  el('refresh').addEventListener('click',()=>location.reload());
  render();
})();
"""

STYLE = """:root{font:15px system-ui,sans-serif;color:#193247;background:#f3f6f8}*{box-sizing:border-box}body{margin:0}main{max-width:1450px;margin:auto;padding:28px 22px}a{color:#17658b}h1{font-size:34px;letter-spacing:-1px;margin:16px 0}h2{font-size:21px}p{line-height:1.6;color:#496171}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:2px}.panel{background:#fff;border:1px solid #d9e2e9;border-radius:12px;padding:20px;margin:22px 0}.heading,.controls,.pager{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.heading{justify-content:space-between}.controls{align-items:end;margin:18px 0}label{display:grid;gap:6px;font-size:13px;font-weight:600}select,button{font:inherit;padding:9px 12px;border:1px solid #afbdc8;border-radius:6px;background:#fff;color:#193247}button{cursor:pointer;background:#edf4f7}button:disabled{opacity:.5;cursor:default}.small,small{font-size:12px;color:#536b7b}small{display:block;margin-top:4px}.requirements{padding:12px;background:#e4f1fa;border-radius:6px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px;text-align:left;border-bottom:1px solid #dce4eb}thead th{vertical-align:bottom}tbody tr:hover{background:#eef5f8}.pager{margin:12px 0}code{overflow-wrap:anywhere;font-size:12px}pre{white-space:pre-wrap}@media(max-width:650px){main{padding:20px 12px}h1{font-size:28px}.panel{padding:14px}select{max-width:100%}.controls label{flex:1 1 140px}th,td{padding:9px}}"""


def build(summary,tasks,output_dir):
    validate(summary,tasks)
    require_active_batches(tasks)
    from counts import NAVIGATION
    payload=dict(summary=summary,tasks=tasks,category_labels=CATEGORIES,status_labels=STATUSES)
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    script=CORE_SCRIPT+'\n'+SCRIPT
    def csp_hash(text):return "'sha256-"+base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()+"'"
    policy="default-src 'none'; script-src "+csp_hash(script)+' '+csp_hash(raw)+"; style-src "+csp_hash(STYLE)+"; base-uri 'none'; form-action 'none'"
    status='Verified within datasets' if summary['grouping_status']=='VERIFIED_WITHIN_DATASETS' else 'Verified cross-source grouping'
    eligibility_note = 'Eligible subject counts use the saved grouping snapshot; see Quality counts for current numeric-series totals.'
    if summary['schema'] == ELIGIBILITY_SUMMARY_SCHEMA:
        evidence = summary['eligibility']
        eligibility_note = ('Eligibility counts checked ' + evidence['assessed_at'] +
                            '. Quality catalogue <code>' + evidence['quality_manifest_sha256'] + '</code>.')
    html='''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="POLICY"><title>Kuina · Unique repair work</title><style>STYLE</style></head>
<body><main><header>NAVIGATION
<h1>Assignments</h1><p>Current ownership and investigations. Collection does not start automatically.</p>
RECOVERY_NOTICE
<p class="small">At least two years of history · 15 minutes or finer · Verified calendar. No unexplained gaps.</p>
</header><details class="panel"><summary>Inventory grouping details</summary><p>An eligible field does not make a whole target eligible.</p><p class="small">ELIGIBILITY_NOTE</p><p class="small">Summary generated SUMMARY_TIME · Task snapshot TASK_TIME.</p><div class="scroll"><table><thead><tr><th>Category</th><th>Stored numeric series</th><th>Repair subjects</th><th>Field groups</th><th>Subjects with eligible data<br><small>At least one numeric field passes</small></th><th>Unresolved identities</th></tr></thead><tbody id="counts"></tbody></table></div></details>
<section class="panel"><div class="heading"><h2>Existing investigation batches</h2><button id="refresh" type="button">Refresh confirmed snapshot</button></div>
<p>Use <a href="sources.html">Find new data</a> for the current market and sector priorities. Existing assignments keep their original scope and history.</p>
<p>Available means unassigned investigation work, not confirmed recoverable data. Confirmed-unrecoverable source batches have been removed. Inspect the private brief before starting.</p>
<div class="controls"><label>I am<select id="identity"><option value="">Choose your name</option></select></label><label>Category<select id="category"><option value="all">All categories</option></select></label><label>Review kind<select id="review-kind"><option value="all">All</option><option value="market">Market prices</option><option value="statistical">Coarse statistical reports</option><option value="identity">Identity review</option><option value="context">Other context</option><option value="unknown">Unclassified</option></select></label><label>Status<select id="status"><option value="all">All statuses</option></select></label><label>Assignee<select id="person"><option value="all">Everyone</option></select></label></div>
<p class="small">Review kind describes the assignment’s subject. Eligibility comes from a separate scientific audit.</p>
<p id="request-note" role="status" aria-live="polite">Selecting your name does not reserve work. A request stays pending until the confirmed snapshot changes.</p>
<div class="heading"><span id="visible-count"></span><div class="pager"><button id="previous" type="button">← Previous</button><span id="page"></span><button id="next" type="button">Next →</button></div></div>
<div class="scroll"><table><thead><tr><th>Batch / category</th><th>Work targets</th><th>Numeric series</th><th>Status</th><th>Assignee</th><th>Blockers</th><th>Action</th></tr></thead><tbody id="queue"></tbody></table></div>
<p class="small">50 batches per page. Blockers and legacy reservations prevent claims. GitHub records working reservations before agents start; private work and reports stay in Kuina. Verified work is a task result; data eligibility requires a matching scientific audit. Follow the <a href="tasks.html">agent instructions</a> only after a confirmed assignment.</p></section>
</main><script id="unique-data" type="application/json">DATA</script><script>SCRIPT</script></body></html>
'''
    replacements=dict(NAVIGATION=NAVIGATION,POLICY=policy,STYLE=STYLE,GROUPING=status,SUMMARY_TIME=summary['generated_at'],TASK_TIME=tasks['generated_at'],MANIFEST=summary['input_manifest_sha256'],ELIGIBILITY_NOTE=eligibility_note,RECOVERY_NOTICE=recovery.work_notice(),DATA=raw,SCRIPT=script)
    html=re.sub('|'.join(replacements),lambda match:replacements[match.group()],html)
    destination=Path(output_dir);destination.mkdir(parents=True,exist_ok=True)
    with (destination/'unique.html').open('x') as stream:stream.write(html)
    return dict(status='LOCAL_STATIC_UNIQUE_DASHBOARD_BUILT',categories=len(summary['categories']),batches=len(tasks['batches']),output=str(destination/'unique.html'),published=False)

"""Closed public source-job projection; no worker notes, paths or observations."""
import json
import re

from coordination.assignment_progress import validated
from coordination.github_assignments import digest, stamp, validate_ledger
from coordination.github_assignments_v2 import Assignments
from coordination.task_manager import require
from coordination.source_jobs import PREFIX
from unique_dashboard import PEOPLE

DEFINITION_SCHEMA = 'kuina-public-source-job-definitions-v1'
SNAPSHOT_SCHEMA = 'kuina-public-source-jobs-v1'
ROW_FIELDS = {'id', 'source_ids', 'provider', 'market', 'sector', 'state', 'stage',
              'assignee', 'assignment_issue', 'definition_sha256'}
STAGES = dict(available=('open', 'open'), assigned=('in_progress', 'reserved'),
              active=('in_progress', 'active'), blocked=('in_progress', 'blocked'),
              awaiting_verification=('finished', 'finished'), verified=('finished', 'verified'))


def validate_definitions(value, sources):
    import acquisition
    acquisition.validate(sources)
    require(type(value) is dict and set(value) == {'schema', 'jobs'} and
            value['schema'] == DEFINITION_SCHEMA and type(value['jobs']) is list and len(value['jobs']) <= 100,
            'Closed source-job definitions required')
    known = {r['id']: r for r in sources['sources']}
    ids, providers, scoped = set(), set(), set()
    for row in value['jobs']:
        require(type(row) is dict and set(row) == {'id', 'source_ids', 'confirmed_at', 'definition_sha256'},
                'Unexpected public source-job fields')
        require(isinstance(row['id'], str) and row['id'].startswith(PREFIX) and
                re.fullmatch('[A-Za-z0-9_-]{1,96}', row['id']) and row['id'] not in ids and
                digest(row['definition_sha256']), 'Invalid source-job ID or definition')
        ids.add(row['id'])
        stamp(row['confirmed_at'])
        require(type(row['source_ids']) is list and 0 < len(row['source_ids']) <= 30, 'Source references required')
        require(all(type(s) is str and s in known and s not in scoped for s in row['source_ids']) and
                len(set(row['source_ids'])) == len(row['source_ids']), 'Unknown or overlapping source scope')
        selected = [known[s] for s in row['source_ids']]
        provider = selected[0]['provider']
        require(all(s['provider'] == provider and s['status'] != 'rejected' for s in selected) and
                provider.casefold() not in providers, 'One confirmed free-provider job required')
        providers.add(provider.casefold())
        scoped.update(row['source_ids'])
    return value


def snapshot(definitions, sources, catalogue, ledger, generated_at, progress=None):
    validate_definitions(definitions, sources)
    validate_ledger(ledger)
    Assignments._validate_started(ledger)
    stamp(generated_at)
    require(catalogue['generation'] == ledger['migration']['catalogue_generation'], 'Source-job generation differs')
    rows = {r['id']: r for r in catalogue['batches'] if r['id'].startswith(PREFIX)}
    require(set(rows) == {r['id'] for r in definitions['jobs']}, 'Public and private confirmed jobs differ')
    known = {s['id']: s for s in sources['sources']}
    advisory = validated(ledger, progress)
    jobs = []
    for definition in definitions['jobs']:
        job_id = definition['id']
        require(rows[job_id]['definition_sha256'] == definition['definition_sha256'] and
                rows[job_id]['assignment_enabled'] is True, 'Confirmed source-job binding differs')
        current = ledger['assignments'].get(job_id)
        status, person, issue = 'available', None, None
        if current is not None:
            require(current['definition_sha256'] == definition['definition_sha256'] and
                    current['catalogue_generation'] == catalogue['generation'], 'Source-job assignment differs')
            status, person, issue = current['status'], current['person'], current['assignment_issue']
            if job_id in advisory:
                status = advisory[job_id]['status']
        selected = [known[s] for s in definition['source_ids']]
        state, stage = STAGES[status]
        jobs.append(dict(id=job_id, source_ids=definition['source_ids'], provider=selected[0]['provider'],
                         market=selected[0]['market'], sector=' / '.join(sorted({s['sector'] for s in selected})),
                         state=state, stage=stage, assignee=person, assignment_issue=issue,
                         definition_sha256=definition['definition_sha256']))
    times = [generated_at] + [r['confirmed_at'] for r in definitions['jobs']]
    times.extend(r['report_at'] for key, r in advisory.items() if key in rows)
    generated_at = max(times, key=stamp).replace('+00:00', 'Z')
    result = dict(schema=SNAPSHOT_SCHEMA, generated_at=generated_at,
                  people=[dict(id=k, name=v) for k, v in PEOPLE.items()], jobs=jobs)
    validate_snapshot(result)
    return result


def validate_snapshot(value):
    require(type(value) is dict and set(value) == {'schema', 'generated_at', 'people', 'jobs'} and
            value['schema'] == SNAPSHOT_SCHEMA, 'Closed source-job snapshot required')
    stamp(value['generated_at'])
    require(value['people'] == [dict(id=k, name=v) for k, v in PEOPLE.items()], 'Source-job roster differs')
    require(type(value['jobs']) is list and len(value['jobs']) <= 100, 'Source-job count exceeds bound')
    seen = set()
    for job in value['jobs']:
        require(type(job) is dict and set(job) == ROW_FIELDS, 'Unexpected public job fields')
        require(type(job['id']) is str and re.fullmatch(r'unique-source-[a-z0-9-]{1,82}', job['id']) and
                job['id'] not in seen and digest(job['definition_sha256']), 'Invalid source-job identity')
        seen.add(job['id'])
        require((job['state'], job['stage']) in set(STAGES.values()), 'Invalid source-job progress')
        require((job['assignee'] is None and job['assignment_issue'] is None) if job['state'] == 'open'
                else (job['assignee'] in PEOPLE and type(job['assignment_issue']) is int and job['assignment_issue'] > 0),
                'Source-job ownership is required')
        require(type(job['source_ids']) is list and 0 < len(job['source_ids']) <= 30 and
                all(type(s) is str and re.fullmatch('[a-z0-9-]{1,96}', s) for s in job['source_ids']),
                'Invalid public source references')
        require(all(type(job[k]) is str and 0 < len(job[k]) <= 2000 and
                    not any(p in job[k] for p in ('/Users/', '/datashare/', '/flash/'))
                    for k in ('provider', 'market', 'sector')), 'Bounded public source labels required')
    require(len(json.dumps(value).encode()) <= 256*1024, 'Source-job snapshot too large')
    return value


def render_assets(sources, definitions, catalogue, ledger, generated_at, progress=None):
    import acquisition
    jobs = snapshot(definitions, sources, catalogue, ledger, generated_at, progress)
    return {'docs/sources.html': acquisition.render(sources, jobs).encode(),
            'docs/source-jobs.json': (json.dumps(jobs, sort_keys=True, separators=(',', ':'))+'\n').encode()}


SCRIPT = r"""(() => {
  const initial = document.getElementById('source-jobs-data');
  if (!initial) return;
  const identity = document.getElementById('source-job-person');
  const list = document.getElementById('source-job-list');
  const note = document.getElementById('source-job-note');
  const stages = {open:'Open',reserved:'Reserved · waiting for agent start',active:'Agent working',blocked:'Blocked · see private report',finished:'Finished collecting · audit pending',verified:'Verified work'};
  let current = JSON.parse(initial.textContent);
  const people = new Map(current.people.map(p => [p.id,p.name]));
  function valid(data) {
    if (!data || data.schema !== 'kuina-public-source-jobs-v1' || !Number.isFinite(Date.parse(data.generated_at)) || !Array.isArray(data.jobs) || data.jobs.length > 100 || JSON.stringify(data.people)!==JSON.stringify(current.people)) throw Error('Invalid source-job snapshot');
    const seen=new Set();
    for (const j of data.jobs) {
      if (!/^unique-source-[a-z0-9-]{1,82}$/.test(j.id) || seen.has(j.id) || !/^[a-f0-9]{64}$/.test(j.definition_sha256) || !Object.hasOwn(stages,j.stage)) throw Error('Invalid source job');
      seen.add(j.id);
      if (!['open','in_progress','finished'].includes(j.state) || (j.state==='open' ? (j.assignee!==null || j.assignment_issue!==null || j.stage!=='open') : (!people.has(j.assignee) || !Number.isSafeInteger(j.assignment_issue) || j.assignment_issue<1))) throw Error('Invalid source owner');
      const previous=current.jobs.find(p=>p.id===j.id);
      if (previous && previous.definition_sha256!==j.definition_sha256) throw Error('Source-job definition changed');
      for (const key of ['provider','sector']) if (typeof j[key]!=='string' || j[key].length>2000) throw Error('Invalid source label');
    }
    return data;
  }
  function claimURL(job) {
    const request={version:1,action:'assign',task_id:job.id,person:identity.value};
    const query=new URLSearchParams({title:'[Kuina claim] '+job.id,body:'<!-- kuina-request-v1\n'+JSON.stringify(request)+'\n-->'});
    return 'https://github.com/wangseann/kuina-data-viewer/issues/new?'+query.toString();
  }
  function instructions(job) {
    const person=job.assignee || identity.value;
    if (!people.has(person)) return 'Choose your name first.';
    const cli='python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" ';
    if (job.state==='open') return 'Submit the GitHub claim and wait for confirmation. Then copy these instructions again.';
    let start='';
    if(job.stage==='reserved') start=cli+'prepare-work '+job.id+' --person '+person+' --assignment-issue '+job.assignment_issue+'\n'+
      'Submit the returned start URL using the original GitHub account; wait for confirmation. On your own Native account, run:\n'+cli+'claim --proof-sha256 PREPARATION_HASH\n';
    if(job.state==='finished') return 'Collection was already reported finished. Read the existing private report; do not start another worker or repeat collection. A matching quality audit is still required.';
    return 'Read AGENT_TASKS.md in the private hub and resolve its current KUINA_TASK_MANAGER and KUINA_TASK_HUB. Resume an existing worker first; never create a second claim.\n'+
      cli+'show '+job.id+'\n'+start+
      cli+'read-batch '+job.id+'\n'+
      'Current source-work policy: https://github.com/wangseann/kuina-data-viewer/blob/main/coordination/SOURCE_JOBS.md#continue-without-coordinator-handoffs\n'+
      'Your confirmed provider assignment and actual Native claim authorize routine work within scope. Do not wait for coordinator admission or plan-verification receipts. This current policy supersedes legacy receipt-handoff wording in frozen job descriptions.\n'+
      'Inspect existing data and overlaps, record your exact scope and bounded resource plan privately, and run your own technical preflight. If metadata cannot establish completeness, use bounded provisional qualification under the current policy; keep observations unfilled and remote. Eligibility still requires a matching independent audit.\n'+
      cli+'report '+job.id+' --person '+person+' --status in_progress --note "Private progress evidence"\n'+
      cli+'report '+job.id+' --person '+person+' --status completed --note "Private artifact hashes, coverage evidence and omissions"\n'+
      'Use --status blocked if qualification or collection cannot finish. Do not put private evidence in GitHub issues. Finished collection awaits a matching eligibility audit.';
  }
  function render() {
    list.replaceChildren();
    for (const job of current.jobs) {
      const card=document.createElement('article');card.className='source-job';
      const title=document.createElement('h3');title.textContent=job.provider;card.append(title);
      const scope=document.createElement('p');scope.textContent=job.sector;card.append(scope);
      const state=document.createElement('strong');state.textContent=({open:'Open',in_progress:'In progress',finished:'Finished'})[job.state]+(job.assignee?' · '+people.get(job.assignee):'');card.append(state);
      const detail=document.createElement('small');detail.textContent=stages[job.stage];card.append(detail);
      if (job.state==='open') {
        const link=document.createElement('a');link.textContent=identity.value?'Claim via GitHub':'Choose your name to claim';
        if (people.has(identity.value)) {link.href=claimURL(job);link.target='_blank';link.rel='noopener noreferrer';}
        card.append(link);
      } else {
        const link=document.createElement('a');link.textContent='Confirmed assignment';link.href='https://github.com/wangseann/kuina-data-viewer/issues/'+job.assignment_issue;card.append(link);
      }
      const copy=document.createElement('button');copy.type='button';copy.textContent='Copy agent instructions';
      copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(instructions(job));note.textContent='Agent instructions copied. Reservations do not start an agent.';}catch{note.textContent='Clipboard unavailable; use the agent guide linked above.';}});card.append(copy);
      list.append(card);
    }
    if (!current.jobs.length) {const empty=document.createElement('p');empty.textContent='No confirmed source jobs published yet.';list.append(empty);}
  }
  identity.addEventListener('change',render);
  document.getElementById('source-job-refresh').addEventListener('click',async()=>{
    try {const response=await fetch('source-jobs.json',{cache:'no-store'});if(!response.ok)throw Error('Unavailable');const raw=await response.text();if(raw.length>262144)throw Error('Too large');const next=valid(JSON.parse(raw));if(Date.parse(next.generated_at)<Date.parse(current.generated_at))throw Error('Older snapshot');current=next;render();note.textContent='Confirmed source-job snapshot refreshed.';}
    catch {note.textContent='Refresh unavailable; retained the last confirmed snapshot.';}
  });
  valid(current);render();
})();"""


def panel(jobs):
    import html
    validate_snapshot(jobs)
    options = ''.join('<option value="'+key+'">'+html.escape(name)+'</option>' for key, name in PEOPLE.items())
    payload = json.dumps(jobs, sort_keys=True, separators=(',', ':')).replace('<', r'\u003c').replace('>', r'\u003e').replace('&', r'\u0026')
    return ('<section id="source-jobs"><h2>Confirmed free-source jobs</h2>'
            '<p>Open → In progress (person) → Finished (person). Inspect existing data and verify coverage before collection. '
            'Finished means the owner reported completion; data eligibility requires a separate audit.</p>'
            '<p>Already claimed? <a href="https://github.com/wangseann/kuina-data-viewer/blob/main/coordination/SOURCE_JOBS.md#continue-without-coordinator-handoffs">Continue without coordinator admission or plan-verification receipts</a>. '
            'Use the existing worker; collection completion and data eligibility are separate.</p>'
            '<p><a href="https://github.com/wangseann/kuina-data-viewer/blob/main/coordination/SOURCE_JOBS.md">Agent setup and posting guide</a> · '
            '<a href="https://github.com/wangseann/kuina-data-viewer/issues/new?title=%5BKuina%20source%20proposal%5D&amp;body=Provider%3A%0AMarket%20and%20sector%3A%0AOfficial%20documentation%20URL%3A%0AFree%20access%20evidence%3A%0ANative%20interval%20and%20history%3A%0ANo%20private%20paths%2C%20credentials%20or%20observations.">Propose a free source</a></p>'
            '<label>I am<select id="source-job-person"><option value="">Choose your name</option>'+options+'</select></label> '
            '<button id="source-job-refresh" type="button">Refresh progress</button>'
            '<p id="source-job-note" role="status">Submit a claim and wait for confirmation before starting. Jobs do not launch agents automatically.</p>'
            '<div id="source-job-list" class="source-job-list"></div></section>'
            '<script id="source-jobs-data" type="application/json">'+payload+'</script>')

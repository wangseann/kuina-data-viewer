'use strict';
const T = KuinaTasks;
const byId = id => document.getElementById(id);
let snapshot = null;
let pageIndex = 0;
let pageCount = 1;
function node(tag,text,className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function addOption(select,value,label) {
  const item = node('option',label);
  item.value = value;
  select.append(item);
}
function issueClass(reason) {
  if (reason === 'coarse_resolution') return 'coarse';
  if (reason === 'short_history') return 'history';
  if (['long_gaps','hourly_gaps','context_gaps','no_window_data','no_valid_observations','missing_months'].includes(reason)) return 'gap';
  return 'other';
}
async function copyCommand(button,text) {
  try { await navigator.clipboard.writeText(text);button.textContent='Copied'; }
  catch { button.textContent='Select command below';button.after(node('pre',text)); }
}
function commandButton(text,command) {
  const button = node('button',text);
  button.addEventListener('click',()=>copyCommand(button,command));
  return button;
}
function requestLink(task,person,action) {
  const link = node('a',action==='assign'?'Claim via GitHub':'Release via GitHub');
  link.href = T.requestURL(task,person,action);
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.addEventListener('click',()=>{
    byId('request-note').textContent='GitHub opened for '+task.id+'. Submit the issue to send your request. It stays pending until the Mac broker confirms it and the refreshed board shows the change. Your GitHub issue records the result.';
  });
  return link;
}
function renderActions(task,person,manual) {
  const actions = node('td');
  if (!manual) {
    actions.append(node('span','Historical snapshot · read only','small'));
    return actions;
  }
  if (task.status === 'available') {
    if (person) actions.append(requestLink(task,person,'assign'));
    else actions.append(node('span','Choose “I am” above to claim','small'));
  } else if (task.status === 'assigned' && task.assignee === person) {
    actions.append(commandButton('Copy agent claim','python3 "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" claim '+task.id+' --person '+person));
    if (Number.isSafeInteger(task.assignment_issue) && task.assignment_issue > 0) {
      const release = node('p');
      release.append(requestLink(task,person,'release'));
      actions.append(release);
    }
  } else if (task.assignee === person) {
    actions.append(commandButton('Copy agent status','python3 "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" show '+task.id));
  }
  if (task.assignment_issue) {
    const origin = node('a','Assignment #'+task.assignment_issue);
    origin.href = 'https://github.com/wangseann/kuina-data-viewer/issues/'+task.assignment_issue;
    origin.target = '_blank';
    origin.rel = 'noopener noreferrer';
    const line = node('p');
    line.append(origin);
    actions.append(line);
  }
  if (!actions.childNodes.length) actions.append(node('span','Assigned work is reserved','small'));
  return actions;
}
function render() {
  if (!snapshot) return;
  const manual = snapshot.schema_version === 3;
  const identity = byId('identity').value;
  const people = new Map(snapshot.people.map(person=>[person.id,person]));
  byId('batch-note').textContent = manual
    ? T.availableRecords(snapshot).toLocaleString()+' review records are available. Choose a batch of at most 500 catalogue records; your agent starts only after its Native claim succeeds.'
    : 'Historical assignments are shown read only. Self-service links appear after the private queue migration.';
  byId('identity').disabled = !manual;
  byId('my-work').disabled = !manual || !identity;
  byId('available-work').disabled = !manual;
  byId('poll-command').textContent='python3 "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" list --person '+(identity||'YOUR_PERSON_ID');
  const maxRecords = Math.max(1,...snapshot.people.map(person=>T.remaining(person,snapshot)));
  byId('people').replaceChildren();
  for (const person of snapshot.people) {
    const records = T.remaining(person,snapshot);
    const card = node('article',undefined,'person');
    card.append(node('h3',person.name),node('span',records.toLocaleString(),'load'),node('p','assigned review records remaining'));
    const track = node('div',undefined,'load-track');
    const bar = node('span');
    bar.style.width=(100*records/maxRecords)+'%';
    track.append(bar);
    card.append(track,node('p',(manual?person.assigned:person.queued)+' assigned · '+person.active+' active'),node('p',person.awaiting_verification+' awaiting verification · '+person.verified+' verified'));
    byId('people').append(card);
  }
  byId('categories').replaceChildren();
  for (const group of T.rollups(snapshot)) {
    const row = node('tr');
    row.append(node('td',T.TYPES[group.category]),node('td',manual?group.available.toLocaleString():'—'),node('td',manual?group.available_records.toLocaleString():'—'),node('td',group.batches?group.verified.toLocaleString()+' / '+group.batches.toLocaleString():'Inventory task'),node('td',group.remaining.toLocaleString()));
    byId('categories').append(row);
  }
  const filters = {person:byId('person').value,category:byId('category').value,status:byId('status').value};
  const priority = {active:0,blocked:1,awaiting_verification:2,assigned:3,available:4,queued:5,verified:6,batched:7};
  const tasks = T.reviewTasks(snapshot,filters).sort((a,b)=>priority[a.status]-priority[b.status]||T.TYPES[a.category].localeCompare(T.TYPES[b.category])||(a.batch_number||0)-(b.batch_number||0)||a.id.localeCompare(b.id));
  const selected = T.page(tasks,pageIndex);
  pageIndex = selected.index;
  pageCount = selected.pages;
  byId('task-count').textContent=tasks.length.toLocaleString()+' matching jobs';
  byId('page').textContent=selected.start.toLocaleString()+'–'+selected.end.toLocaleString()+' of '+tasks.length.toLocaleString();
  byId('previous').disabled=pageIndex===0;
  byId('next').disabled=pageIndex+1>=pageCount;
  byId('task-list').replaceChildren();
  for (const task of selected.rows) {
    const row = node('tr');
    const name = node('td',T.TYPES[task.category]);
    if (task.parent_id) name.append(node('small','Batch '+task.batch_number.toLocaleString()+' / '+task.batch_total.toLocaleString()));
    name.append(node('span',task.id,'task-id'));
    row.append(name,node('td',task.assignee?people.get(task.assignee).name:'Unassigned'),node('td',T.KINDS[task.kind]));
    const progress = node('td');
    progress.append(node('span',T.STATUSES[task.status],'status '+task.status));
    row.append(progress,node('td',task.affected_series.toLocaleString()));
    const issues = node('td');
    if (task.issues.length) {
      const details = node('details');
      details.append(node('summary',task.issues.length+' warning types'));
      for (const reason of task.issues) details.append(node('span',(KuinaReasons[reason]||['Other check'])[0],'issue '+issueClass(reason)));
      issues.append(details);
    } else issues.append(node('span','Inventory check','small'));
    row.append(issues,renderActions(task,identity,manual));
    byId('task-list').append(row);
  }
  if (!tasks.length) {
    const row = node('tr');
    const cell = node('td','No tasks match these filters.');
    cell.colSpan=7;
    row.append(cell);
    byId('task-list').append(row);
  }
}
async function refresh() {
  byId('refresh').disabled=true;
  try {
    const response = await fetch('tasks-summary.json',{cache:'no-store'});
    if (!response.ok) throw Error('Shared task snapshot is not available yet.');
    const raw = await response.text();
    if (raw.length > 16*1024*1024) throw Error('Task snapshot is too large.');
    snapshot = T.validate(JSON.parse(raw));
    if (snapshot.schema_version !== 3 && byId('status').value === 'available') byId('status').value='all';
    render();
    byId('sync').className=T.stale(snapshot.updated_at)?'error':'';
    byId('sync').textContent='Confirmed snapshot: '+new Date(snapshot.updated_at).toLocaleString()+'. '+(T.stale(snapshot.updated_at)?'More than 24 hours old. Requests are checked against the current private queue.':'GitHub requests appear here after broker confirmation and the next snapshot sync.');
  } catch (error) {
    snapshot = null;
    byId('task-list').replaceChildren();
    byId('task-count').textContent='Queue unavailable';
    byId('sync').textContent=error.message;
    byId('sync').className='error';
  } finally { byId('refresh').disabled=false; }
}
for (const id of T.PEOPLE) {
  const name = id==='th'?'TH':id[0].toUpperCase()+id.slice(1);
  addOption(byId('person'),id,name);
  addOption(byId('identity'),id,name);
}
for (const [id,label] of Object.entries(T.TYPES)) addOption(byId('category'),id,label);
for (const [id,label] of Object.entries(T.STATUSES)) addOption(byId('status'),id,label);
byId('status').value='available';
for (const id of ['person','category','status','identity']) byId(id).addEventListener('change',()=>{pageIndex=0;render();});
byId('my-work').addEventListener('click',()=>{byId('person').value=byId('identity').value;byId('status').value='all';pageIndex=0;render();});
byId('available-work').addEventListener('click',()=>{byId('person').value='all';byId('status').value='available';pageIndex=0;render();});
byId('previous').addEventListener('click',()=>{pageIndex--;render();});
byId('next').addEventListener('click',()=>{pageIndex++;render();});
byId('refresh').addEventListener('click',refresh);
refresh();
setInterval(refresh,15*60*1000);

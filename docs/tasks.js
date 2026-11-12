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
function addOption(select,value,label) { const item=node('option',label);item.value=value;select.append(item); }
function issueClass(reason) {
  if (reason === 'coarse_resolution') return 'coarse';
  if (reason === 'short_history') return 'history';
  if (['long_gaps','hourly_gaps','context_gaps','no_window_data','no_valid_observations','missing_months'].includes(reason)) return 'gap';
  return 'other';
}
async function copyCommand(button,text) {
  try { await navigator.clipboard.writeText(text);button.textContent='Copied'; }
  catch { button.textContent='Select command below';const code=node('pre',text);button.after(code); }
}
function render() {
  if (!snapshot) return;
  byId('batch-note').textContent=snapshot.schema_version===2?'Review batches contain at most 500 saved catalogue records. Batch assignments are balanced by outstanding record count; the dataset leads remain the same.':'This snapshot still contains the original category jobs. Bounded batches appear after the private queue migration.';
  const people = new Map(snapshot.people.map(person => [person.id,person]));
  const maxLoad = Math.max(1,...snapshot.people.map(person=>T.remaining(person,snapshot)));
  byId('people').replaceChildren();
  for (const person of snapshot.people) {
    const records=T.remaining(person,snapshot);
    const card=node('article',undefined,'person');card.append(node('h3',person.name),node('span',records.toLocaleString(),'load'),node('p','review records outstanding'));
    const track=node('div',undefined,'load-track'),bar=node('span');bar.style.width=(100*records/maxLoad)+'%';track.append(bar);card.append(track);
    card.append(node('p',person.queued+' queued · '+person.active+' active'),node('p',person.awaiting_verification+' awaiting verification · '+person.verified+' verified'));
    byId('people').append(card);
  }
  byId('leads').replaceChildren();
  for(const group of T.rollups(snapshot)) {
    const row=node('tr');
    row.append(node('td',T.TYPES[group.category]),node('td',people.get(group.lead).name),node('td',group.batches?group.verified.toLocaleString()+' / '+group.batches.toLocaleString():'Inventory / unsplit task'),node('td',group.records.toLocaleString()),node('td',group.remaining.toLocaleString()));
    byId('leads').append(row);
  }
  const filters={person:byId('person').value,category:byId('category').value,status:byId('status').value};
  const tasks=T.reviewTasks(snapshot,filters).sort((a,b)=>T.TYPES[a.category].localeCompare(T.TYPES[b.category])||(a.batch_number||0)-(b.batch_number||0)||a.id.localeCompare(b.id));
  const selected=T.page(tasks,pageIndex);pageIndex=selected.index;pageCount=selected.pages;
  byId('task-count').textContent=tasks.length.toLocaleString()+' matching jobs';
  byId('page').textContent=selected.start.toLocaleString()+'–'+selected.end.toLocaleString()+' of '+tasks.length.toLocaleString();
  byId('previous').disabled=pageIndex===0;byId('next').disabled=pageIndex+1>=pageCount;
  byId('task-list').replaceChildren();
  for (const task of selected.rows) {
    const row=node('tr'),identity=node('td',T.TYPES[task.category]);
    if(task.parent_id)identity.append(node('small','Batch '+task.batch_number.toLocaleString()+' / '+task.batch_total.toLocaleString()));
    identity.append(node('span',task.id,'task-id'));
    const owner=node('td',people.get(task.assignee).name);owner.append(node('small','Lead: '+people.get(task.lead||task.assignee).name));
    row.append(identity,owner,node('td',T.KINDS[task.kind]));
    const progress=node('td');progress.append(node('span',T.STATUSES[task.status],'status '+task.status));row.append(progress,node('td',task.affected_series.toLocaleString()));
    const issues=node('td'),details=node('details');
    details.append(node('summary',task.issues.length+' warning types'));
    for (const reason of task.issues) details.append(node('span',(KuinaReasons[reason]||['Other check'])[0],'issue '+issueClass(reason)));
    if(task.issues.length)issues.append(details);else issues.append(node('span','Inventory check','small'));
    row.append(issues);
    const actions=node('td'),button=node('button',task.status==='queued'?'Copy claim command':'Copy status command');
    const command='python3 "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" '+(task.status==='queued'?'claim '+task.id+' --person '+task.assignee:'show '+task.id);
    button.addEventListener('click',()=>copyCommand(button,command));actions.append(button);row.append(actions);byId('task-list').append(row);
  }
  if (!tasks.length) {const row=node('tr'),cell=node('td','No tasks match these filters.');cell.colSpan=7;row.append(cell);byId('task-list').append(row);}
}
async function refresh() {
  byId('refresh').disabled=true;
  try {
    const response=await fetch('tasks-summary.json',{cache:'no-store'});
    if (!response.ok) throw Error('Shared task snapshot is not available yet.');
    const raw=await response.text();if(raw.length>16*1024*1024)throw Error('Task snapshot is too large.');
    snapshot=T.validate(JSON.parse(raw));render();
    byId('sync').className=T.stale(snapshot.updated_at)?'error':'';
    byId('sync').textContent='Snapshot: '+new Date(snapshot.updated_at).toLocaleString()+'. '+(T.stale(snapshot.updated_at)?'More than 24 hours old — check the private queue before acting.':'Check the private queue before claiming; this page cannot reserve tasks.');
  } catch (error) {byId('sync').textContent=error.message;byId('sync').className='error';}
  finally {byId('refresh').disabled=false;}
}
for (const id of T.PEOPLE) addOption(byId('person'),id,id==='th'?'TH':id[0].toUpperCase()+id.slice(1));
for (const [id,label] of Object.entries(T.TYPES)) addOption(byId('category'),id,label);
for (const [id,label] of Object.entries(T.STATUSES)) addOption(byId('status'),id,label);
for (const id of ['person','category','status']) byId(id).addEventListener('change',()=>{pageIndex=0;render();});
byId('previous').addEventListener('click',()=>{pageIndex--;render();});
byId('next').addEventListener('click',()=>{pageIndex++;render();});
byId('refresh').addEventListener('click',refresh);
refresh();

setInterval(refresh,15*60*1000);

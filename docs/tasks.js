'use strict';
const T = KuinaTasks;
const byId = id => document.getElementById(id);
let snapshot = null;
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
  const people = new Map(snapshot.people.map(person => [person.id,person]));
  const maxLoad = Math.max(1,...snapshot.people.map(person=>person.load));
  byId('people').replaceChildren();
  for (const person of snapshot.people) {
    const card=node('article',undefined,'person');card.append(node('h3',person.name),node('span',person.load+' effort points','load'));
    const track=node('div',undefined,'load-track'),bar=node('span');bar.style.width=(100*person.load/maxLoad)+'%';track.append(bar);card.append(track);
    card.append(node('p',person.queued+' queued · '+person.active+' active'),node('p',person.awaiting_verification+' awaiting verification · '+person.verified+' verified'));
    byId('people').append(card);
  }
  const filters={person:byId('person').value,category:byId('category').value,status:byId('status').value};
  const tasks=snapshot.tasks.filter(task=>T.matches(task,filters)).sort((a,b)=>T.TYPES[a.category].localeCompare(T.TYPES[b.category])||a.id.localeCompare(b.id));byId('task-count').textContent=tasks.length+' of '+snapshot.tasks.length+' tasks';
  byId('task-list').replaceChildren();
  for (const task of tasks) {
    const row=node('tr'),identity=node('td',T.TYPES[task.category]);identity.append(node('span',task.id,'task-id'));row.append(identity,node('td',people.get(task.assignee).name),node('td',T.KINDS[task.kind]+' · '+task.effort+' points'));
    const progress=node('td');progress.append(node('span',T.STATUSES[task.status],'status '+task.status));row.append(progress,node('td',task.affected_series.toLocaleString()));
    const issues=node('td'),details=node('details');
    details.append(node('summary',task.issues.length+' warning types'));
    for (const reason of task.issues) details.append(node('span',(KuinaReasons[reason]||['Other check'])[0],'issue '+issueClass(reason)));
    if(task.issues.length)issues.append(details);else issues.append(node('span','Inventory check','small'));
    row.append(issues);
    const actions=node('td'),button=node('button',task.status==='queued'?'Copy claim command':'Copy status command');
    const command='python3 "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" '+(task.status==='queued'?'claim '+task.id+' --person '+task.assignee:'list --person '+task.assignee);
    button.addEventListener('click',()=>copyCommand(button,command));actions.append(button);row.append(actions);byId('task-list').append(row);
  }
  if (!tasks.length) {const row=node('tr'),cell=node('td','No tasks match these filters.');cell.colSpan=7;row.append(cell);byId('task-list').append(row);}
}
async function refresh() {
  byId('refresh').disabled=true;
  try {
    const response=await fetch('tasks-summary.json',{cache:'no-store'});
    if (!response.ok) throw Error('Shared task snapshot is not available yet.');
    const raw=await response.text();if(raw.length>2*1024*1024)throw Error('Task snapshot is too large.');
    snapshot=T.validate(JSON.parse(raw));render();
    byId('sync').className=T.stale(snapshot.updated_at)?'error':'';
    byId('sync').textContent='Snapshot: '+new Date(snapshot.updated_at).toLocaleString()+'. '+(T.stale(snapshot.updated_at)?'More than 24 hours old — check the private queue before acting.':'Check the private queue before claiming; this page cannot reserve tasks.');
  } catch (error) {byId('sync').textContent=error.message;byId('sync').className='error';}
  finally {byId('refresh').disabled=false;}
}
for (const id of T.PEOPLE) addOption(byId('person'),id,id==='th'?'TH':id[0].toUpperCase()+id.slice(1));
for (const [id,label] of Object.entries(T.TYPES)) addOption(byId('category'),id,label);
for (const [id,label] of Object.entries(T.STATUSES)) addOption(byId('status'),id,label);
for (const id of ['person','category','status']) byId(id).addEventListener('change',render);
byId('refresh').addEventListener('click',refresh);
refresh();

setInterval(refresh,15*60*1000);

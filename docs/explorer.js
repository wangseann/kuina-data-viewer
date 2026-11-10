/* Browser-only private file reader. No network requests or collection actions. */
'use strict';
const K = KuinaInspection;
const $ = id => document.getElementById(id);
const state = {manifest:null,files:new Map(),records:[],selected:null,preview:null,page:0,generation:0,chunk:0,browse:false,cache:new Map(),legacyPages:new Map(),legacyPreviews:new Map()};
const ROWS = 40;
const TYPE_LABELS = {stocks:'Stocks / ETFs',crypto:'Crypto',commodities:'Commodities',currencies:'Currencies',derivatives:'Derivatives',economics:'Economics',gdelt:'GDELT / news','prediction-markets':'Prediction markets',sentiment:'Tweets / Sentiments',emotions:'Emotions',trade:'Trade',weather:'Weather / rivers',reddit:'Reddit','other-markets':'Indices / bonds / other'};
function element(tag,text,className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function message(text,error=false) { $('load-status').textContent=text; $('load-status').className=error?'error':''; }
function interval(seconds) {
  if (!(seconds>0)) return 'Not established';
  if (seconds<60) return seconds+' seconds';
  if (seconds<3600) return seconds/60+' minutes';
  if (seconds<86400) return seconds/3600+' hours';
  return seconds/86400+' days';
}
function option(select,value,label) { const node=element('option',label); node.value=value; select.append(node); }
function dataset() { return state.manifest.datasets.find(item=>item.id===$('dataset').value); }
function clearDetail() {
  state.selected=null;state.preview=null;$('selected-title').textContent='Choose a series';$('selected-source').textContent='';$('preview-note').textContent='';$('checks').replaceChildren();$('brief').disabled=true;$('brief-status').textContent='';drawChart();
}
function reset() {
  state.generation++;state.records=[];state.page=0;state.cache.clear();state.files.clear();state.legacyPages.clear();state.legacyPreviews.clear();state.manifest=null;
  $('workspace').hidden=true;clearDetail();
}
async function unpack(blob,compressed,limit=32*1024*1024) {
  let stream=blob.stream();
  if (compressed) stream=stream.pipeThrough(new DecompressionStream('gzip'));
  const reader=stream.getReader(),chunks=[];let total=0;
  try {
    while (true) {
      const {value,done}=await reader.read();if(done)break;
      total+=value.byteLength;if(total>limit)throw Error('Decoded file exceeds the browser size limit');chunks.push(value);
    }
  } catch(error) { await reader.cancel();throw error; }
  return JSON.parse(await new Blob(chunks).text());
}
async function readAsset(reference) {
  const path=K.safePath(reference.path),file=state.files.get(path);
  if (!file) throw Error('Package file is missing: '+path);
  if (file.size!==reference.bytes || file.size>32*1024*1024) throw Error('Package file size changed: '+path);
  const bytes=await file.arrayBuffer();
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  if (hash!==reference.sha256) throw Error('Package file does not match its saved fingerprint: '+path);
  return unpack(new Blob([bytes]),path.endsWith('.gz'));
}
async function readPage(reference) {
  if(state.legacyPages.has(reference.path))return state.legacyPages.get(reference.path);
  const page=await readAsset(reference);
  if(page.schema!=='kuina-series-page-v1'||page.datasetId!==dataset().id||!Array.isArray(page.series)||page.series.length>1000)throw Error('Invalid series catalogue page');
  return page.series;
}
function activate() {
  $('workspace').hidden=false;
  $('audit-date').textContent=state.manifest.legacy?'Earlier preview · current eligibility not linked':'Source audit: '+state.manifest.auditUtc;
  $('requirements').textContent='Required window: '+state.manifest.windowStart+' to '+state.manifest.windowEnd+' (end excluded). At least two years of usable history and original values every 15 minutes or more often.';
  resetChartDates();
  $('type').replaceChildren();
  for(const id of Object.keys(TYPE_LABELS)) {
    const total=state.manifest.datasets.filter(item=>item.type===id).reduce((sum,item)=>sum+item.series,0);
    option($('type'),id,TYPE_LABELS[id]+' · '+total.toLocaleString()+' series in this package');
  }
  const requested=new URLSearchParams(location.hash.slice(1)).get('type');
  const first=state.manifest.datasets.find(item=>item.type===requested)||state.manifest.datasets[0];if(first)$('type').value=first.type;
  chooseType();
}
function chooseType() {
  state.generation++;clearDetail();$('dataset').replaceChildren();
  const choices=state.manifest.datasets.filter(item=>item.type===$('type').value);
  for(const item of choices)option($('dataset'),item.id,item.label+' · '+item.series.toLocaleString());
  if(!choices.length){state.records=[];state.browse=false;state.page=0;$('results').textContent='No identified series of this type in this package. This does not prove that no source files exist.';renderRows();return;}
  search();
}
async function search() {
  const selected=dataset();if(!selected)return;
  const generation=++state.generation;state.records=[];state.page=0;clearDetail();renderRows();
  $('results').textContent='Searching the selected source…';
  const term=$('search').value,filter=$('quality').value;
  if(filter==='eligible'&&selected.eligible===0){state.browse=false;$('results').textContent='No eligible series in this source’s saved audit. Choose “Needs fixing” or “All series” to inspect its problems.';renderRows();return;}
  state.browse=!term.trim();state.chunk=0;
  if(state.browse){await browseChunk(0,generation);return;}
  try {
    for(let index=0;index<selected.pages.length;index++) {
      const records=await readPage(selected.pages[index]);if(generation!==state.generation)return;
      state.records.push(...records.filter(record=>K.matches(record,term,filter)));
      // Only metadata for matches is retained; chart arrays are loaded separately.
      if(state.records.length>100000)throw Error('More than 100,000 matches. Narrow the name, variable or quality filter.');
      $('results').textContent=state.records.length.toLocaleString()+' matching series · searched '+(index+1)+' / '+selected.pages.length+' catalogue pages';
      await new Promise(resolve=>setTimeout(resolve,0));
    }
    if(generation!==state.generation)return;
    $('results').textContent=state.records.length.toLocaleString()+' matches out of '+selected.series.toLocaleString()+' series in this source. All series remain accessible through search; only 40 rows are displayed at once.';
    renderRows();await loadVisiblePreviews(generation);
  }catch(error){if(generation===state.generation)message(error.message,true);}
}
async function browseChunk(index,generation=state.generation) {
  const selected=dataset();
  try {
    state.chunk=index;state.page=0;
    const records=await readPage(selected.pages[index]);if(generation!==state.generation)return;
    state.records=records.filter(record=>K.matches(record,'',$('quality').value));
    $('results').textContent=selected.series.toLocaleString()+' series in this source · catalogue section '+(index+1)+' / '+selected.pages.length+'. Browse sections or search the entire source by name or variable.';
    renderRows();await loadVisiblePreviews(generation);
  }catch(error){if(generation===state.generation)message(error.message,true);}
}
function visible() { return state.records.slice(state.page*ROWS,(state.page+1)*ROWS); }
function statusSquare(record) {
  const square=element('span',undefined,'row-square');
  const colours=K.eligible(record)?[K.COLOURS.complete]:[[1,'missing'],[2,'coarse'],[4,'outside'],[8,'unknown']].filter(([bit])=>K.mask(record)&bit).map(([,name])=>K.COLOURS[name]);
  if(!colours.length)colours.push(K.COLOURS.unknown);
  const bands=colours.map((colour,index)=>colour+' '+index/colours.length*100+'% '+(index+1)/colours.length*100+'%');
  square.style.background=colours.length===1?colours[0]:'linear-gradient(90deg,'+bands.join(',')+')';
  square.title=K.eligible(record)?'All mandatory checks passed':(record.checks||[]).filter(check=>check.status==='FAIL').map(check=>(KuinaReasons[check.reason]||['Other failed check'])[0]).join('; ');
  return square;
}
function renderRows() {
  const body=$('series-list');body.replaceChildren();
  for(const record of visible()) {
    const row=element('tr');row.tabIndex=0;if(state.selected?.id===record.id)row.className='selected';
    const name=element('td',record.label);name.append(element('small',record.variable));row.append(name);
    const status=element('td');status.append(statusSquare(record),element('span',K.eligible(record)?'Eligible':(state.manifest.legacy?'Earlier snapshot · not a current pass':'Needs fixing'),K.eligible(record)?'badge complete':'badge unknown'));row.append(status);
    row.append(element('td',interval(record.nativeSeconds)),element('td',(record.historyStart||'Unknown')+' → '+(record.historyEnd||'Unknown')),element('td',record.preview?'Available':'Not generated / unavailable'));
    row.addEventListener('click',()=>select(record));row.addEventListener('keydown',event=>{if(event.key==='Enter')select(record);});body.append(row);
  }
  const pages=Math.max(1,Math.ceil(state.records.length/ROWS));$('page').textContent=(state.browse?'Section '+(state.chunk+1)+' · ':'')+(state.page+1)+' / '+pages;$('previous').disabled=state.page===0&&(!state.browse||state.chunk===0);$('next').disabled=(state.page+1)>=pages&&(!state.browse||state.chunk+1>=dataset().pages.length);
  drawHeatmap();
}
async function preview(record) {
  if(state.legacyPreviews.has(record.id))return state.legacyPreviews.get(record.id);
  if(!record.preview)return null;
  const key=record.preview.path;
  if(!state.cache.has(key)) {
    if(state.cache.size>=3)state.cache.delete(state.cache.keys().next().value);
    const currentManifest=state.manifest;
    const result=await readAsset(record.preview);
    if(currentManifest!==state.manifest)return null;
    if(result.schema!=='kuina-series-preview-v1'||result.windowStart!==state.manifest.windowStart||result.windowEnd!==state.manifest.windowEnd||!result.series)throw Error('Preview window or schema does not match the catalogue');
    for(const data of Object.values(result.series))if(!Array.isArray(data.points)||data.points.length>4096)throw Error('Preview has too many chart points');
    state.cache.set(key,result);
  }
  return state.cache.get(key).series[record.id]||null;
}
async function loadVisiblePreviews(generation=state.generation) {
  for(const record of visible()) {
    try {
      record.display=await preview(record);if(generation!==state.generation)return;drawHeatmap();
    }catch(error){if(generation===state.generation){$('heat-detail').textContent=error.message;record.display=null;}}
  }
}
async function select(record) {
  const generation=state.generation;state.selected=record;state.preview=null;renderRows();
  $('selected-title').textContent=record.label+' · '+record.variable;
  $('selected-source').textContent=[record.source,record.datasetName,interval(record.nativeSeconds),'units: '+(record.units||'Not established'),record.quoteSide,record.priceConstruction,record.adjustment].filter(Boolean).join(' · ');
  $('brief').disabled=K.eligible(record)||state.manifest.legacy;$('brief-status').textContent='';$('checks').replaceChildren();
  const failures=(record.checks||[]).filter(check=>check.status==='FAIL');
  if(!failures.length)$('checks').append(element('p',K.eligible(record)?'All mandatory checks passed in this saved audit.':'No completed current eligibility result is available.'));
  for(const check of failures) {
    const explanation=KuinaReasons[check.reason]||['Other failed check','Inspect the saved audit evidence before treating this series as usable.'];
    const box=element('div',undefined,'failure failure-'+(K.REASON_BITS[check.reason]||8));box.append(element('strong',explanation[0]),element('p',explanation[1]));
    if(check.evidence!==undefined&&check.evidence!==null)box.append(element('p','Saved evidence: '+JSON.stringify(check.evidence),'small'));
    $('checks').append(box);
  }
  try {
    const data=await preview(record);if(generation!==state.generation||state.selected?.id!==record.id)return;
    state.preview=data;
    $('preview-note').textContent=data?'Daily summaries of recorded values for display; no filling. The original recording interval is shown above. '+(data.note||''):'No verified preview has been generated for this series. Its chart and exact daily gaps cannot be inferred from its first and last dates.';
    drawChart();
  }catch(error){if(state.selected?.id===record.id){$('preview-note').textContent=error.message;drawChart();}}
}
function canvas(id,height) {
  const node=$(id),width=Math.max(id==='heatmap'?700:280,node.getBoundingClientRect().width),ratio=devicePixelRatio||1;
  node.width=Math.round(width*ratio);node.height=Math.round(height*ratio);node.style.height=height+'px';const context=node.getContext('2d');context.scale(ratio,ratio);context.clearRect(0,0,width,height);return {node,context,width,height};
}
function drawHeatmap() {
  if(!state.manifest)return;
  const rows=visible(),days=K.dates(state.manifest.windowStart,state.manifest.windowEnd),{context:c,width}=canvas('heatmap',50+rows.length*20),left=Math.min(235,width*.28),cell=(width-left)/days.length;
  c.font='11px system-ui';c.fillStyle='#3c5262';
  days.forEach((date,index)=>{if(date.endsWith('-01')&&[1,4,7,10].includes(Number(date.slice(5,7))))c.fillText(date.slice(0,7),left+index*cell,14);});
  rows.forEach((record,row)=>{
    c.fillStyle='#193247';c.fillText((record.label+' · '+record.variable).slice(0,32),0,37+row*20);
    const cells=record.display?.days||{};
    days.forEach((date,index)=>{const shade=K.coverageState(record,cells[date]||record.display?.defaultDay,date);c.fillStyle=K.COLOURS[shade];c.fillRect(left+index*cell,24+row*20,Math.max(cell,1),15);});
  });
  $('heatmap').onmousemove=event=>{const rect=$('heatmap').getBoundingClientRect(),x=(event.clientX-rect.left)*width/rect.width,y=event.clientY-rect.top,row=Math.floor((y-24)/20),day=Math.floor((x-left)/cell);if(row<0||row>=rows.length||day<0||day>=days.length)return;const record=rows[row],date=days[day],info=record.display?.days?.[date]||record.display?.defaultDay;$('heat-detail').textContent=record.label+' · '+record.variable+' · '+date+' · '+K.coverageState(record,info,date)+' · covered 15-minute intervals: '+(info?.observed??'not measured')+' / '+(info?.expected??'not established')+' · native records: '+(info?.nativeRecorded??'not measured');};
  $('heatmap').onclick=event=>{const rect=$('heatmap').getBoundingClientRect(),row=Math.floor((event.clientY-rect.top-24)/20),day=Math.floor(((event.clientX-rect.left)*width/rect.width-left)/cell);if(rows[row]){if(day>=0&&day<days.length){$('chart-start').value=days[Math.max(0,day-7)];$('chart-end').value=days[Math.min(days.length-1,day+7)];}select(rows[row]);}};
}
function resetChartDates() {
  if(!state.manifest)return;
  $('chart-start').value=state.manifest.windowStart;
  $('chart-end').value=new Date(Date.parse(state.manifest.windowEnd)-K.DAY).toISOString().slice(0,10);
}
function drawChart() {
  const {context:c,width,height}=canvas('chart',320),start=Date.parse($('chart-start').value||state.manifest?.windowStart),end=Date.parse($('chart-end').value||state.manifest?.windowEnd)+K.DAY;
  const points=(state.preview?.points||[]).filter(point=>Number.isFinite(point.value)&&Date.parse(point.time)>=start&&Date.parse(point.time)<end);
  if(end<=start){$('chart-detail').textContent='Choose an end date on or after the start date.';return;}
  if(!points.length){c.fillStyle='#526b7b';c.font='14px system-ui';c.fillText(state.selected?'No recorded preview values in these dates.':'Choose a series with a recorded-value preview.',18,45);$('chart-detail').textContent='';return;}
  const values=points.flatMap(point=>[point.value,point.min,point.max].filter(Number.isFinite));let low=Math.min(...values),high=Math.max(...values);if(low===high){low-=1;high+=1;}
  const x=time=>65+(Date.parse(time)-start)/(end-start)*(width-85),y=value=>25+(high-value)/(high-low)*(height-65);
  c.strokeStyle='#d5e0e7';c.strokeRect(65,25,width-85,height-65);c.font='11px system-ui';c.fillStyle='#3c5262';c.fillText(high.toPrecision(5),0,30);c.fillText(low.toPrecision(5),0,height-40);c.fillText($('chart-start').value,65,height-12);c.fillText($('chart-end').value,width-95,height-12);
  c.strokeStyle='#a0c9bc';for(const point of points){if(Number.isFinite(point.min)&&Number.isFinite(point.max)){c.beginPath();c.moveTo(x(point.time),y(point.min));c.lineTo(x(point.time),y(point.max));c.stroke();}}
  c.strokeStyle='#25826b';c.lineWidth=1.5;let previous=null;
  for(const point of points){c.beginPath();if(previous&&Date.parse(point.time)-Date.parse(previous.time)<=K.DAY*1.5){c.moveTo(x(previous.time),y(previous.value));c.lineTo(x(point.time),y(point.value));}else{c.arc(x(point.time),y(point.value),2,0,2*Math.PI);}c.stroke();previous=point;}
  $('chart-detail').textContent=points.length+' recorded daily summaries. Vertical marks show each day’s range when available. Lines break across days without recorded values.';
}
async function loadLegacy(file) {
  const generation=state.generation;
  if(file.size>80*1024*1024)throw Error('Earlier HTML exceeds the 80 MiB limit');
  const text=await file.text(),match=text.match(/<script\b[^>]*\bid=["']payload["'][^>]*>([\s\S]*?)<\/script>/i);
  if(!match)throw Error('No supported saved chart payload found. The selected HTML is never executed.');
  const encoded=match[1].trim();if(!/^[A-Za-z0-9+/=\s]+$/.test(encoded))throw Error('Invalid compressed chart payload');
  const bytes=Uint8Array.from(atob(encoded),char=>char.charCodeAt(0)),data=await unpack(new Blob([bytes]),true,256*1024*1024);
  if(generation!==state.generation)return;
  if(!Array.isArray(data.series)||data.series.length>20000)throw Error('Unsupported earlier viewer');
  const days=K.dates(data.window_start,data.window_end_exclusive),groups=new Map();
  for(const bundle of data.series) {
    const type=bundle.group==='Crypto'?'crypto':bundle.group==='Sentiment'?'sentiment':'stocks',key=type+'|'+bundle.source;
    if(!groups.has(key))groups.set(key,{id:key,type,label:bundle.source,series:0,pages:[],records:[]});
    const group=groups.get(key),fields=type==='sentiment'?['signal']:bundle.fields;
    for(const field of fields) {
      const id=bundle.id+'|'+field,checks=[{id:'current_audit',status:'FAIL',reason:'input_identity_unverified',evidence:'Earlier visual extraction; current audit version is not linked'}];
      if(bundle.native_seconds>900)checks.push({id:'required_cadence',status:'FAIL',reason:'coarse_resolution',evidence:bundle.native_seconds});
      const record={id,dataset:key,label:bundle.label,variable:type==='sentiment'?'sentiment_halfgaussian_mean':field,source:bundle.source,nativeSeconds:bundle.native_seconds,units:bundle.quote||'See original source',historyStart:null,historyEnd:null,decision:'INELIGIBLE',checks,preview:{path:'legacy/'+id}};
      const daily=bundle.daily,coverage={},points=[];
      days.forEach((date,index)=>{const expected=daily.expected?.[index],observed=daily.observed?.[index];coverage[date]={checked:Number.isInteger(expected)&&Number.isInteger(observed),expected,observed,longestGapSeconds:null};const value=daily[field]?.[index];if(Number.isFinite(value))points.push({time:date,value,min:type==='sentiment'?daily.signal_low?.[index]:null,max:type==='sentiment'?daily.signal_high?.[index]:null});});
      state.legacyPreviews.set(id,{days:coverage,points,note:'Historical preview only. Current source identity and eligibility have not been linked to this file.'});group.records.push(record);group.series++;
    }
  }
  const datasets=[...groups.values()];
  for(const group of datasets){for(let offset=0;offset<group.records.length;offset+=1000){const path='legacy-page/'+group.id+'/'+offset;state.legacyPages.set(path,group.records.slice(offset,offset+1000));group.pages.push({path});}delete group.records;}
  state.manifest={legacy:true,schema:'kuina-inspection-v1',auditUtc:null,windowStart:data.window_start,windowEnd:data.window_end_exclusive,requirements:{maxNativeSeconds:900,minHistoryYears:2},datasets};
  message('Earlier chart data loaded locally. Its old pass labels are excluded from current eligibility.');activate();
}
$('folder').addEventListener('change',async event=>{reset();const generation=state.generation;try{const files=[...event.target.files],manifests=files.filter(file=>file.name==='inspection-manifest.json');if(manifests.length!==1)throw Error('Choose one package folder containing exactly one inspection-manifest.json');const manifest=manifests[0];if(manifest.size>16*1024*1024)throw Error('Manifest exceeds the 16 MiB limit');const prefix=manifest.webkitRelativePath.slice(0,-manifest.name.length);const data=K.validateManifest(JSON.parse(await manifest.text()));if(generation!==state.generation)return;for(const file of files){if(file.webkitRelativePath.startsWith(prefix))state.files.set(file.webkitRelativePath.slice(prefix.length),file);}state.manifest=data;message('Private package opened locally. Only the chosen source’s files are read.');activate();}catch(error){if(generation===state.generation)message(error.message,true);}});
$('legacy').addEventListener('change',async event=>{reset();try{if(event.target.files[0])await loadLegacy(event.target.files[0]);}catch(error){message(error.message,true);}});
$('type').addEventListener('change',chooseType);$('dataset').addEventListener('change',search);$('find').addEventListener('click',search);$('quality').addEventListener('change',search);$('search').addEventListener('keydown',event=>{if(event.key==='Enter')search();});
for(const [id,delta]of [['previous',-1],['next',1]])$(id).addEventListener('click',async()=>{const generation=++state.generation,nextPage=state.page+delta;if(state.browse&&(nextPage<0||nextPage*ROWS>=state.records.length)){await browseChunk(state.chunk+delta,generation);if(generation!==state.generation)return;if(delta<0){state.page=Math.max(0,Math.ceil(state.records.length/ROWS)-1);renderRows();loadVisiblePreviews(generation);}return;}state.page=nextPage;renderRows();loadVisiblePreviews(generation);});
$('brief').addEventListener('click',()=>{if(!state.selected||state.manifest.legacy)return;const brief=K.repairBrief(state.selected,state.manifest,KuinaReasons),blob=new Blob([JSON.stringify(brief,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=element('a');link.href=url;link.download='kuina-repair-'+state.selected.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('brief-status').textContent='Repair brief downloaded. Give it to your agent; green status still requires a new verified audit.';});
window.addEventListener('resize',()=>{drawHeatmap();drawChart();});
for(const id of ['chart-start','chart-end'])$(id).addEventListener('change',drawChart);
$('chart-reset').addEventListener('click',()=>{resetChartDates();drawChart();});

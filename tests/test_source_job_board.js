const fs=require('fs'),vm=require('vm'),assert=require('assert');
function element(){return {children:[],listeners:{},value:'',textContent:'',append(x){this.children.push(x)},replaceChildren(...xs){this.children=xs},addEventListener(k,fn){this.listeners[k]=fn}};}
const snapshot=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const elements={};
for(const key of ['source-jobs-data','source-job-person','source-job-list','source-job-note','source-job-refresh'])elements[key]=element();
elements['source-jobs-data'].textContent=JSON.stringify(snapshot);
let copied='',response=snapshot;
const document={getElementById:k=>elements[k],createElement:()=>element()};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{document,URLSearchParams,console,navigator:{clipboard:{writeText:async v=>{copied=v}}},fetch:async()=>({ok:true,text:async()=>JSON.stringify(response)})});
const cards=()=>elements['source-job-list'].children;
const link=(i)=>cards()[i].children.find(x=>x.textContent==='Claim via GitHub'||x.textContent==='Choose your name to claim');
assert.equal(cards().length,3);
assert(!link(0).href,'Selecting a person is required');
elements['source-job-person'].value='juan';elements['source-job-person'].listeners.change();
const url=new URL(link(0).href);
assert.equal(url.hostname,'github.com');
assert.equal(url.searchParams.get('title'),'[Kuina claim] '+snapshot.jobs[0].id);
const request=JSON.parse(url.searchParams.get('body').split('\n')[1]);
assert.equal(request.person,'juan');assert.equal(request.action,'assign');
assert.equal(snapshot.jobs[0].state,'open','Opening the form must not claim work optimistically');
async function test(){
  await cards()[1].children.find(x=>x.textContent==='Copy agent instructions').listeners.click();
  assert(copied.includes('prepare-work'));assert(copied.includes('--person seann'));assert(copied.includes('--assignment-issue 42'));
  response=JSON.parse(JSON.stringify(snapshot));response.jobs[1].stage='active';
  await elements['source-job-refresh'].listeners.click();
  await cards()[1].children.find(x=>x.textContent==='Copy agent instructions').listeners.click();
  assert(!copied.includes('prepare-work'),'An existing worker must not prepare another claim');
  assert(copied.includes('--status completed'));
  assert(copied.includes('Do not wait for coordinator admission or plan-verification receipts'),
    'Claimed source owners must receive the self-service policy, not a second approval handoff');
  assert(copied.includes('coordination/SOURCE_JOBS.md'), 'Copy the authoritative current source policy');
  assert(copied.includes('bounded provisional qualification'), 'Explain how to check content when metadata is insufficient');
  assert(!copied.includes('source admission must pass'), 'Do not restore the retired manual handoff');
  await cards()[2].children.find(x=>x.textContent==='Copy agent instructions').listeners.click();
  assert(!copied.includes('prepare-work'));assert(copied.includes('already reported finished'));
  response={schema:'bad'};
  await elements['source-job-refresh'].listeners.click();
  assert.equal(cards().length,3,'Invalid refresh must retain reservations');
  assert(elements['source-job-note'].textContent.includes('retained'));
}
test().catch(e=>{console.error(e);process.exitCode=1});

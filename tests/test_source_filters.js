const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const make=()=>({value:'all',listeners:{},children:[],addEventListener(type,fn){this.listeners[type]=fn},replaceChildren(...items){this.children=items;this.value=items[0].value},append(item){this.children.push(item)}});
const elements={'market-filter':make(),'sector-filter':make(),'status-filter':make(),'visible-count':{textContent:''}};
const rows=[
  {dataset:{market:'futures',sector:'Metals',status:'metadata_needed'}},
  {dataset:{market:'futures',sector:'Agriculture',status:'access_required'}},
  {dataset:{market:'stocks',sector:'Utilities',status:'metadata_needed'}}
];
const document={getElementById:id=>elements[id],querySelectorAll:()=>rows};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{document,Option:function(text,value){this.text=text;this.value=value}});
assert.equal(elements['visible-count'].textContent,'3 provider / sector investigations');
elements['market-filter'].value='futures';elements['market-filter'].listeners.change();
assert.deepEqual(rows.map(r=>r.hidden),[false,false,true]);
assert.deepEqual(elements['sector-filter'].children.map(x=>x.value),['all','Agriculture','Metals']);
elements['sector-filter'].value='Metals';elements['sector-filter'].listeners.change();
assert.deepEqual(rows.map(r=>r.hidden),[false,true,true]);
elements['status-filter'].value='access_required';elements['status-filter'].listeners.change();
assert(rows.every(r=>r.hidden));
elements['market-filter'].value='all';elements['status-filter'].value='all';elements['market-filter'].listeners.change();
assert(rows.every(r=>!r.hidden));

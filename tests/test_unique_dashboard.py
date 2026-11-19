"""Closed metadata and static claim behavior for the unique-work dashboard."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import unique_dashboard as dashboard


def fixtures():
    summary=dict(schema='kuina-unique-public-summary-v1',generated_at='2026-11-18T01:00:00Z',input_manifest_sha256='a'*64,grouping_status='VERIFIED_WITHIN_DATASETS',categories=[dict(id='stocks',stored_numeric_series=30,unique_work_targets=10,distinct_measurement_groups=20,targets_with_saved_eligible_fields=3,unresolved_identity_targets=2)])
    tasks=dict(schema='kuina-unique-public-tasks-v1',generated_at='2026-11-18T01:00:00Z',people=[dict(id=i,name=n) for i,n in dashboard.PEOPLE.items()],batches=[dict(id='unique-stocks-001',category='stocks',target_count=2,series_count=6,status='available',assignee=None,assignment_issue=None,blocker_codes=[])])
    return summary,tasks


class UniqueDashboardTests(unittest.TestCase):
    def test_builds_only_standalone_html_without_mutating_inputs(self):
        summary,tasks=fixtures();before=deepcopy((summary,tasks))
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'docs'
            result=dashboard.build(summary,tasks,output)
            self.assertEqual({p.name for p in output.iterdir()},{'unique.html'})
            html=(output/'unique.html').read_text()
            self.assertEqual(result['batches'],1)
            self.assertIn('900 seconds',html)
            self.assertIn('two years',html)
            self.assertIn('No unexplained gaps',html)
            self.assertIn('Subjects with eligible data',html)
            self.assertIn('does not make a whole target eligible',html)
            self.assertIn('tasks.html',html)
            self.assertIn('Review kind',html)
            self.assertIn('id="review-kind"',html)
        self.assertEqual((summary,tasks),before)

    def test_rejects_freeform_private_fields_and_unknown_roster_names(self):
        for field,value in [('private_path','/flash/private'),('notes','raw observation'),('uid','public-user-id')]:
            summary,tasks=fixtures();tasks['batches'][0][field]=value
            with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();tasks['people'][0]['name']='Someone else'
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();tasks['people'].pop()
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)

    def test_rejects_unverified_grouping_invalid_counts_and_bad_batch_scope(self):
        for field,value in [('grouping_status','CANDIDATE'),('input_manifest_sha256','bad')]:
            summary,tasks=fixtures();summary[field]=value
            with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        for field,value in [('unique_work_targets',31),('targets_with_saved_eligible_fields',11),('stored_numeric_series',True),('unresolved_identity_targets',-1)]:
            summary,tasks=fixtures();summary['categories'][0][field]=value
            with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();tasks['batches'][0]['category']='private-dataset'
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)

    def test_rejects_duplicate_batches_unknown_blockers_and_overlarge_snapshot(self):
        summary,tasks=fixtures();tasks['batches']*=2
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();tasks['batches'][0]['blocker_codes']=['freeform-details']
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();tasks['batches']*=20001
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)

    def test_claim_url_matches_existing_github_request_fields(self):
        summary,tasks=fixtures()
        result=self.run_js(summary,tasks,"console.log(JSON.stringify(U.requestURL(data.tasks.batches[0],'olga')))")
        from urllib.parse import urlparse,parse_qs
        parsed=urlparse(result)
        self.assertEqual(parsed.scheme+'://'+parsed.netloc+parsed.path,'https://github.com/wangseann/kuina-data-viewer/issues/new')
        params=parse_qs(parsed.query)
        self.assertEqual(params['title'],['[Kuina claim] unique-stocks-001'])
        self.assertEqual(params['body'],['<!-- kuina-request-v1\n'+json.dumps(dict(version=1,action='assign',task_id='unique-stocks-001',person='olga'),separators=(',',':'))+'\n-->'])

    def test_claims_only_available_unblocked_batches_and_roster_people(self):
        summary,tasks=fixtures()
        script="""const b=data.tasks.batches[0]; const out=[];
        for(const status of ['assigned','active','blocked','awaiting_verification','verified']){try{U.requestURL({...b,status},'juan');out.push(false)}catch{out.push(true)}}
        for(const x of [{...b,blocker_codes:['identity_review']},{...b,assignee:'juan'}]){try{U.requestURL(x,'juan');out.push(false)}catch{out.push(true)}}
        try{U.requestURL(b,'outsider');out.push(false)}catch{out.push(true)}
        console.log(JSON.stringify(out));"""
        self.assertEqual(self.run_js(summary,tasks,script),[True]*8)

    def test_filters_category_status_and_person(self):
        summary,tasks=fixtures()
        script="""const b={...data.tasks.batches[0],status:'active',assignee:'juan'};
        console.log(JSON.stringify([U.matches(b,{category:'stocks',status:'active',person:'juan'}),U.matches(b,{category:'all',status:'all',person:'olga'}),U.matches(b,{category:'all',status:'all',person:'all'})]));"""
        self.assertEqual(self.run_js(summary,tasks,script),[True,False,True])

    def test_claim_opens_pending_note_without_assignment_or_fetch_mutation(self):
        self.assertIn('Pending until the confirmed snapshot is refreshed',dashboard.SCRIPT)
        self.assertNotIn('fetch(',dashboard.SCRIPT)
        self.assertNotIn('.status =',dashboard.SCRIPT)
        self.assertNotIn('innerHTML',dashboard.SCRIPT)

    def test_malformed_nested_metadata_is_rejected_as_validation_failure(self):
        for field,value in [('id',[]),('category',{}),('status',[]),('assignee',[])]:
            summary,tasks=fixtures();tasks['batches'][0][field]=value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):dashboard.validate(summary,tasks)
        summary,tasks=fixtures();summary['categories'][0]['id']=[]
        with self.assertRaises(ValueError):dashboard.validate(summary,tasks)

    def test_confirmed_assignment_exposes_only_the_selected_assignees_literal_claim_command(self):
        summary,tasks=fixtures()
        script="""const b={...data.tasks.batches[0],status:'assigned',assignee:'seann',assignment_issue:17};
        console.log(JSON.stringify([U.workerCommand(b,'seann'),U.workerCommand(b,'olga'),
          U.workerCommand({...b,status:'available'},'seann'),U.workerCommand({...b,assignee:null},'seann')]));"""
        expected='python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" prepare-work \'unique-stocks-001\' --person \'seann\' --assignment-issue 17'
        self.assertEqual(self.run_js(summary,tasks,script),[expected,None,None,None])

    def test_existing_own_work_gets_readonly_show_and_never_another_claim(self):
        summary,tasks=fixtures()
        script="""const b={...data.tasks.batches[0],assignee:'seann',assignment_issue:null};
        console.log(JSON.stringify(['active','blocked','awaiting_verification'].map(status=>U.workerCommand({...b,status},'seann'))));"""
        expected='python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" show \'unique-stocks-001\''
        self.assertEqual(self.run_js(summary,tasks,script),[expected]*3)

    def test_worker_command_rejects_missing_confirmation_unknown_people_and_shell_payloads(self):
        summary,tasks=fixtures()
        script="""const b={...data.tasks.batches[0],status:'assigned',assignee:'seann',assignment_issue:17};
        const bad=[null,{},[],Object.assign([],{...b}),{...b,status:'verified'},{...b,status:'unknown'},
          ...[null,0,-1,1.5,true,'17',NaN,Infinity,9007199254740992].map(assignment_issue=>({...b,assignment_issue})),
          ...['', 'a'.repeat(97), 'task;touch-secret', "task'quoted", 'task$(uname)', 'task`uname`', 'task\\n', 'task name', 'task/../id'].map(id=>({...b,id}))];
        console.log(JSON.stringify([...bad.map(x=>U.workerCommand(x,'seann')),U.workerCommand(b,'outsider'),
          U.workerCommand({...b,status:'active',assignment_issue:'bad'},'seann')]));"""
        self.assertTrue(all(value is None for value in self.run_js(summary,tasks,script)))

    def test_agent_button_reveals_plain_command_and_identity_change_clears_it(self):
        for status,issue,action in [('assigned',17,"prepare-work 'unique-stocks-001' --person 'seann' --assignment-issue 17"),
                                    ('active',None,"show 'unique-stocks-001'")]:
            summary,tasks=fixtures();tasks['batches'][0].update(status=status,assignee='seann',assignment_issue=issue)
            setup=self.dom_setup()
            interaction="""const buttons=commandButtons(ids.queue);const beforeHidden=descendants(ids.queue,'pre')[0].hidden;
            buttons[0].listeners.click();
            const revealed={count:buttons.length,hidden:descendants(ids.queue,'pre')[0].hidden,command:descendants(ids.queue,'code')[0].textContent};
            ids.identity.value='olga';ids.identity.listeners.change();
            console.log(JSON.stringify({beforeHidden,revealed,after:{count:commandButtons(ids.queue).length,
              hidden:descendants(ids.queue,'code').length===0,command:descendants(ids.queue,'code')[0]?.textContent||''}}));"""
            result=self.run_js(summary,tasks,setup+'\n'+dashboard.SCRIPT+'\n'+interaction)
            with self.subTest(status=status):
                self.assertTrue(result['beforeHidden'])
                self.assertEqual(result['revealed'],dict(count=1,hidden=False,command='python3 -B "$KUINA_TASK_MANAGER" --hub "$KUINA_TASK_HUB" '+action))
                self.assertEqual(result['after'],dict(count=0,hidden=True,command=''))

    def test_review_kind_uses_only_exact_readable_ids_and_handles_hyphenated_categories(self):
        summary,tasks=fixtures()
        script="""const id=(category,mode,planning)=>'unique-'+category+'-'+mode+'-'+planning+'-0123456789abcdef-000001';
        const cases=[
          ['commodities','fao','statistical'],['commodities','psd','statistical'],['commodities','prices','review'],
          ['stocks','equities','review'],['currencies','fx','review'],['stocks','mixed-prices','review'],
          ['stocks','cross-source','review'],['sentiment','cross-source','review'],
          ['other-markets','cross-source','review'],['prediction-markets','series','review'],
          ['weather','geo','review'],['trade','ports','review'],['sentiment','accounts','review'],
          ['economics','wide','review'],['commodities','identity','identity']];
        console.log(JSON.stringify(cases.map(([category,mode,planning])=>U.reviewKind({category,id:id(category,mode,planning)}))));"""
        self.assertEqual(self.run_js(summary,tasks,script),[
            'statistical','statistical','market','market','market','market','market','context',
            'market','context','context','context','context','context','identity'])

    def test_review_kind_unknown_fallback_and_filter_composition_preserve_claim_state(self):
        summary,tasks=fixtures()
        script="""const b={...data.tasks.batches[0],category:'commodities',
          id:'unique-commodities-prices-review-0123456789abcdef-000001'};
        const unknown=[null,{},b.id,Object.assign([],{...b}),{...b,id:'unique-commodities-001'},{...b,category:'stocks'},
          {...b,id:b.id+'\\n'},{...b,id:b.id.replace('prices','new-mode')},
          {...b,id:b.id.replace('0123456789abcdef','0123456789abcdeg')},
          {...b,id:b.id.slice(0,-1)},{...b,category:'made-up'}];
        const before=JSON.stringify(b), available=U.claimable(b);
        const filters={category:'commodities',status:'available',person:'all',kind:'market'};
        const matched=[U.matches(b,filters),U.matches(b,{...filters,kind:'statistical'}),
          U.matches(b,{...filters,category:'stocks'}),U.matches(b,{...filters,status:'assigned'}),
          U.matches(b,{...filters,person:'seann'})];
        console.log(JSON.stringify({unknown:unknown.map(x=>U.reviewKind(x)),matched,
          unchanged:JSON.stringify(b)===before&&U.claimable(b)===available}));"""
        self.assertEqual(self.run_js(summary,tasks,script),dict(unknown=['unknown']*11,
            matched=[True,False,False,False,False],unchanged=True))

    def test_review_kind_dropdown_hides_statistics_keeps_market_pagination_and_clears_command(self):
        summary,tasks=fixtures();summary['categories'][0].update(id='commodities',stored_numeric_series=135,
            unique_work_targets=135,distinct_measurement_groups=135,targets_with_saved_eligible_fields=0,unresolved_identity_targets=0)
        def batch(mode,planning,number,own=False):
            return dict(id='unique-commodities-'+mode+'-'+planning+'-0123456789abcdef-'+str(number).zfill(6),
                category='commodities',target_count=1,series_count=1,status='assigned' if own else 'available',
                assignee='seann' if own else None,assignment_issue=17 if own else None,blocker_codes=[])
        tasks['batches']=[batch('prices','review',1,True)]+[batch('fao','statistical',number) for number in range(1,81)]+[
            batch('prices','review',number) for number in range(2,56)]
        dashboard.validate(summary,tasks)
        interaction="""commandButtons(ids.queue)[0].listeners.click();
          ids['review-kind'].value='market';ids['review-kind'].listeners.change();
          const first={rows:descendants(ids.queue,'tr').length,page:ids.page.textContent,
            count:ids['visible-count'].textContent,onlyMarket:descendants(ids.queue,'tr').every(row=>row.children[0].textContent.startsWith('unique-commodities-prices-review-')),
            commandCleared:descendants(ids.queue,'pre')[0].hidden&&descendants(ids.queue,'code')[0].textContent===''};
          ids.next.listeners.click();const second={rows:descendants(ids.queue,'tr').length,page:ids.page.textContent};
          ids.person.value='seann';ids.person.listeners.change();
          console.log(JSON.stringify({first,second,own:{rows:descendants(ids.queue,'tr').length,page:ids.page.textContent}}));"""
        result=self.run_js(summary,tasks,self.dom_setup()+'\n'+dashboard.SCRIPT+'\n'+interaction)
        self.assertEqual(result,dict(first=dict(rows=50,page='Page 1 / 2',count='55 matching batches',onlyMarket=True,commandCleared=True),
            second=dict(rows=5,page='Page 2 / 2'),own=dict(rows=1,page='Page 1 / 1')))

    def dom_setup(self):
        return """class Element {
              constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.value='all';this.hidden=false;this.text='';}
              set textContent(value){this.text=String(value);this.children=[];}
              get textContent(){return this.text+this.children.map(child=>child.textContent).join('');}
              append(...children){this.children.push(...children);}
              replaceChildren(...children){this.children=[...children];}
              addEventListener(name,handler){this.listeners[name]=handler;}
            }
            const ids=Object.fromEntries(['unique-data','identity','person','category','status','counts','queue',
              'visible-count','page','previous','next','refresh','request-note','review-kind'].map(id=>[id,new Element(id)]));
            ids.identity.value='seann';
            ids['unique-data'].textContent=JSON.stringify({summary:data.summary,tasks:data.tasks,
              category_labels:Object.fromEntries(data.summary.categories.map(category=>[category.id,category.id])),
              status_labels:{assigned:'Assigned',active:'In progress',available:'Available'}});
            globalThis.document={getElementById:id=>ids[id],createElement:tag=>new Element(tag)};
            function descendants(node,tag){return [...(node.tag===tag?[node]:[]),
              ...node.children.flatMap(child=>descendants(child,tag))];}
            function commandButtons(node){return descendants(node,'button').filter(button=>button.textContent==='Agent command');}
            """

    def run_js(self,summary,tasks,statement):
        code='const data='+json.dumps(dict(summary=summary,tasks=tasks))+';\n'+dashboard.CORE_SCRIPT+'\nconst U=KuinaUnique;\n'+statement
        response=subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)
        return json.loads(response.stdout)


if __name__=='__main__':unittest.main()

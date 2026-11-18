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
            self.assertIn('Saved eligible fields',html)
            self.assertIn('does not make a whole target eligible',html)
            self.assertIn('tasks.html',html)
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

    def run_js(self,summary,tasks,statement):
        code='const data='+json.dumps(dict(summary=summary,tasks=tasks))+';\n'+dashboard.CORE_SCRIPT+'\nconst U=KuinaUnique;\n'+statement
        response=subprocess.run(['node','-e',code],check=True,capture_output=True,text=True)
        return json.loads(response.stdout)


if __name__=='__main__':unittest.main()

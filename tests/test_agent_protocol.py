"""Public dual-queue instructions match actual private CLI behavior."""
import contextlib,hashlib,io,json,tempfile,unittest
from pathlib import Path
from coordination.github_claims import parse_request
from coordination.task_manager import Hub,PEOPLE,digest,write
from coordination.unique_queue import UniqueQueue
from coordination.unique_task_manager import Manager,main

ROOT=Path(__file__).resolve().parents[1]

def protocol():return json.loads((ROOT/'docs/agent-protocol.json').read_text())

class AgentProtocolTests(unittest.TestCase):
    def test_new_default_counts_subjects_and_retains_original_variants_and_legacy(self):
        p=protocol();self.assertEqual(p['schema'],'kuina-agent-coordination-v4')
        self.assertEqual(p['default_queue'],'unique')
        self.assertEqual(p['review_batches']['maximum_repair_subjects'],100)
        self.assertTrue(p['review_batches']['all_original_fields_and_variants_retained'])
        self.assertEqual(p['queues']['legacy']['maximum_catalogue_records'],500)
        self.assertTrue(p['queues']['legacy']['existing_claims_and_reports_preserved'])
        self.assertTrue(p['queues']['unique']['requires_coordinator_activation'])
        self.assertEqual(p['queues']['unique']['page'],'unique.html')
        self.assertEqual(p['queues']['legacy']['page'],'tasks.html')
    def test_transport_roster_requirements_privacy_and_claim_boundary_unchanged(self):
        p=protocol();self.assertEqual({v['id']:v['name']for v in p['participants']},PEOPLE)
        self.assertEqual(len(p['participants']),11)
        self.assertEqual(p['requirements'],dict(max_native_interval_seconds=900,minimum_calendar_years=2,unexplained_gaps_allowed=0))
        self.assertFalse(p['claims']['website_creates_worker_claim']);self.assertFalse(p['claims']['automatic_expiry'])
        r=p['assignment_requests'];payload=dict(version=r['version'],action='assign',task_id='unique-example',person='juan')
        issue=dict(number=17,title='[Kuina claim] unique-example',body='<!-- '+r['marker']+'\n'+json.dumps(payload)+'\n-->',user={'login':'volunteer'})
        self.assertEqual(parse_request(issue),payload)
        text=json.dumps(p)
        for forbidden in ('/datashare/','/flash/','/Users/','/home/','11198'):
            self.assertNotIn(forbidden,text)
    def test_published_snapshot_names_and_private_context_lookup_are_explicit(self):
        p=protocol();self.assertEqual(p['public_snapshot'],'unique-tasks.json')
        self.assertEqual(p['queues']['unique']['summary'],'unique-summary.json')
        self.assertEqual(p['queues']['legacy']['snapshot'],'tasks-summary.json')
        self.assertIn('target_id',p['private_context_lookup'])
        self.assertIn('series_ids',p['private_context_lookup'])
        self.assertNotIn('context',p['commands'])
        self.assertIn('--include-legacy',p['commands']['list_work'])
    def test_advertised_cli_routes_unique_work_and_resumes_legacy_without_reclaim(self):
        p=protocol()
        with tempfile.TemporaryDirectory()as temporary:
            base=Path(temporary).resolve();hub=Hub(base/'hub');hub.init()
            for task_id in ('leaf-unique','legacy-resume'):
                task=dict(id=task_id,category='stocks',kind='triage',assignee='juan',effort=1,affected_series=2,issues=[],created_at='2026-01-01T00:00:00+00:00',scope=None)
                write(hub.root/'tasks'/(task_id+'.json'),task)
            hub.enable_self_service();hub.claim('legacy-resume','juan')
            legacy_path,_=hub.work_claim_record(hub.task('legacy-resume'));owner_before=(legacy_path/'owner.json').read_bytes()
            source=base/'input';source.mkdir();body=dict(schema='kuina-unique-batch-v1',id='unique-example',targets=[dict(target_id='subject-example',legacy_tasks=[dict(id='leaf-unique',task_sha256=digest(hub.task('leaf-unique')))],series_ids=['original-open','original-close'])])
            raw=json.dumps(body).encode();(source/'batch.json').write_bytes(raw)
            manifest=dict(schema='kuina-unique-queue-v1',batches=[dict(id='unique-example',category='stocks',target_count=1,series_count=2,file=dict(path='batch.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))])
            (source/'manifest.json').write_text(json.dumps(manifest));parent=hub.root/'unique-work';parent.mkdir()
            queue=UniqueQueue(parent/'generation1',hub);installed=queue.install(source/'manifest.json')
            write(hub.root/'unique-work.json',dict(schema_version=1,queue_root=str(queue.root),manifest_sha256=installed['manifest_sha256']))
            manager=Manager(hub.root);manager.assign('unique-example','juan',17,'volunteer')
            def execute(name,task='unique-example'):
                replacements={'TASK_ID':task,'PERSON_ID':'juan','PRIVATE_NOTE':'Synthetic fixture provenance'}
                args=[replacements.get(value,value)for value in p['commands'][name]]
                with contextlib.redirect_stdout(io.StringIO())as output:main(['--hub',str(hub.root),*args])
                return json.loads(output.getvalue())
            rows=execute('list_work');self.assertEqual({r['id']for r in rows},{'unique-example','legacy-resume'})
            execute('claim');batch=execute('read_batch')
            self.assertEqual(batch['targets'][0]['series_ids'],['original-open','original-close'])
            execute('report');execute('report','legacy-resume')
            self.assertEqual(execute('show','legacy-resume')['status'],'active')
            self.assertEqual((legacy_path/'owner.json').read_bytes(),owner_before)

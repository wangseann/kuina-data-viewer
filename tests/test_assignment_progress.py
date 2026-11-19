"""Real private claim/report to advisory public status; no service calls."""
import copy,json,unittest
from coordination.assignment_publication import task_snapshot,render_assets
import test_github_task_manager as private
import test_unique_dashboard

class ProgressTests(unittest.TestCase):
 def setUp(self):
  self.f=private.ManagerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.prep,_=self.f.working();self.at='2026-11-19T00:00:00Z'
  row=self.f.catalogue.row(self.f.batch)
  self.assignment=dict(batch_id=self.f.batch,person='seann',author='seann',assignment_issue=42,status='active',definition_sha256=row['file']['sha256'],catalogue_generation=self.f.fixture.generation,created_at=self.at,updated_at=self.at,origin='github',work_proof_sha256=self.prep['proof_sha256'],working_request_issue=43)
  def receipt(issue,action,status):return dict(request_issue=issue,batch_id=self.f.batch,action=action,person='seann',author='seann',assignment_issue=42 if action=='working' else None,proof_sha256=self.prep['proof_sha256'] if action=='working' else None,status=status,recorded_at=self.at,definition_sha256=row['file']['sha256'],catalogue_generation=self.f.fixture.generation,origin='github')
  self.ledger=dict(schema='kuina-github-assignments-v1',migration=dict(complete=True,source_sha256='a'*64,catalogue_generation=self.f.fixture.generation),assignments={self.f.batch:self.assignment},receipts={'42':receipt(42,'assign','confirmed'),'43':receipt(43,'working','started')})
  self.summary,_=test_unique_dashboard.fixtures()
  self.catalogue=dict(schema='kuina-public-assignment-catalogue-v1',generation=self.f.fixture.generation,batches=[dict(id=self.f.batch,category=row['category'],target_count=row['target_count'],series_count=row['series_count'],definition_sha256=row['file']['sha256'],assignment_enabled=True)])
 def progress(self):
  from coordination.assignment_progress import requests
  return self.f.manager.progress(requests(self.ledger))
 def test_real_completed_report_reaches_html_json_without_releasing_ledger(self):
  self.f.manager.report(self.f.batch,'seann','completed','SECRET NOTE /private/path')
  result=self.progress();before=copy.deepcopy(self.ledger)
  tasks=task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=result)
  self.assertEqual(tasks['batches'][0]['status'],'awaiting_verification')
  assets=render_assets(self.summary,self.catalogue,self.ledger,self.at,progress=result)
  self.assertEqual(json.loads(assets['docs/unique-tasks.json'])['batches'][0]['status'],'awaiting_verification')
  self.assertIn(b'awaiting_verification',assets['docs/unique.html']);self.assertEqual(self.ledger,before)
  raw=json.dumps(result);self.assertNotIn('SECRET',raw);self.assertNotIn('uid',raw);self.assertNotIn('/private',raw);self.assertNotIn('note',raw)
 def test_blocked_and_wrong_proof_or_old_ledger_retains_active(self):
  self.f.manager.report(self.f.batch,'seann','blocked','private')
  result=self.progress();self.assertEqual(task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=result)['batches'][0]['status'],'blocked')
  for key,value in [('preparation_sha256','0'*64),('assignment_issue',99),('catalogue_generation','0'*64)]:
   bad=copy.deepcopy(result);bad['records'][0][key]=value
   self.assertEqual(task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=bad)['batches'][0]['status'],'active')
 def test_missing_private_proof_and_extra_private_key_never_release(self):
  owner=self.f.fixture.hub.root/'work-claims'/self.f.batch/'owner.json';owner.unlink()
  self.assertEqual(self.progress()['records'],[])
  result=dict(schema='kuina-assignment-progress-v1',records=[dict(self.assignment,note='SECRET')])
  self.assertEqual(task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=result)['batches'][0]['status'],'active')

 def test_invalid_status_private_keys_future_and_duplicate_envelopes_retain_active(self):
  self.f.manager.report(self.f.batch,'seann','blocked','PRIVATE')
  good=self.progress()
  for key,value in [('status','available'),('status','verified'),('report_at','2999-01-01T00:00:00Z'),('uid',123),('note','PRIVATE')]:
   bad=copy.deepcopy(good);bad['records'][0][key]=value
   self.assertEqual(task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=bad)['batches'][0]['status'],'active')
  bad=copy.deepcopy(good);bad['records']*=2
  self.assertEqual(task_snapshot(self.summary,self.catalogue,self.ledger,self.at,progress=bad)['batches'][0]['status'],'active')
 def test_cli_closed_binding_and_private_journal_race(self):
  import subprocess,sys
  from pathlib import Path
  from unittest.mock import patch
  from coordination.assignment_progress import requests
  self.f.manager.report(self.f.batch,'seann','blocked','NEVER PUBLIC')
  request=requests(self.ledger)
  command=Path(private.__file__).resolve().parents[1]/'coordination/github_task_manager.py'
  result=subprocess.run([sys.executable,'-B',str(command),'--hub',str(self.f.fixture.hub.root),'progress','--requests-json',json.dumps(request)],capture_output=True)
  self.assertEqual(result.returncode,0,result.stderr);self.assertNotIn(b'NEVER PUBLIC',result.stdout)
  original=self.f.manager.worker_state;calls=[]
  def change(*args,**kwargs):
   value=original(*args,**kwargs);calls.append(1)
   if len(calls)==2:
    path=self.f.fixture.hub.root/'work-claims'/self.f.batch
    (path/'.report-lock').mkdir()
   return value
  with patch.object(self.f.manager,'worker_state',side_effect=change):self.assertEqual(self.progress()['records'],[])
 def test_late_dependency_deletion_or_mutation_omits_advisory(self):
  from pathlib import Path
  from unittest.mock import patch
  import coordination.github_task_manager as module
  from coordination.github_legacy import CombinedWorkProtocol
  self.f.manager.report(self.f.batch,'seann','completed','PRIVATE')
  protocol=CombinedWorkProtocol(self.f.manager.catalogue())
  paths=[protocol.preparation_path(self.prep['proof_sha256']),
         self.f.fixture.hub.root/'work-claims'/self.f.batch/'owner.json',
         protocol.authorization_path(self.f.batch)]
  for path in paths:
   for action in ('delete','mutate'):
    original=path.read_bytes();mode=path.stat().st_mode & 0o7777
    state=self.f.manager.worker_state;reader=module.file_bytes;passes=[];changed=[]
    def checked(*args,**kwargs):
     value=state(*args,**kwargs);passes.append(1);return value
    def read_then_change(target,*args,**kwargs):
     raw=reader(target,*args,**kwargs)
     if len(passes)>=2 and Path(target).name.startswith('report-') and not changed:
      if action=='delete':path.unlink()
      else:path.write_bytes(original+b' ')
      changed.append(True)
     return raw
    with self.subTest(path=path.name,action=action),patch.object(self.f.manager,'worker_state',side_effect=checked),patch.object(module,'file_bytes',side_effect=read_then_change):
     self.assertEqual(self.progress()['records'],[])
     self.assertTrue(changed)
    path.write_bytes(original);path.chmod(mode)
 def test_progress_pages_are_byte_and_count_bounded(self):
  from coordination.assignment_progress import pages,MAX_RECORDS,MAX_JSON_BYTES
  ledger=copy.deepcopy(self.ledger)
  for i in range(80):
   item=dict(self.assignment,batch_id='unique-stocks-'+str(i)+'x'*80);ledger['assignments'][item['batch_id']]=item
  chunks=list(pages(ledger));self.assertEqual(sum(map(len,chunks)),81)
  self.assertTrue(all(len(p)<=MAX_RECORDS and len(json.dumps(p).encode())<=MAX_JSON_BYTES for p in chunks))

class SyncProgressTests(unittest.TestCase):
 setUp = ProgressTests.setUp
 progress = ProgressTests.progress
 # The actual Git fixture separately verifies provider failure and authority CAS.
 def test_real_git_publication_after_private_completion_and_ledger_change_hold(self):
  import test_assignment_sync as git
  from coordination.assignment_sync import Synchronizer
  fixture=git.GitSyncTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  fixture.ledger=self.ledger;fixture.catalogue=self.catalogue;fixture.summary=self.summary
  fixture.write_ledger(fixture.b);fixture.commit(fixture.b,'authority start');fixture.run_git(fixture.b,'push','origin','main')
  self.f.manager.report(self.f.batch,'seann','completed','PRIVATE')
  def provider(observed):
   self.assertEqual(observed['ledger'],self.ledger)
   return self.progress()
  sync=Synchronizer(fixture.a,fixture.gh,expected_origins=(str(fixture.bare),),progress_provider=provider)
  outcome=sync.publish(self.summary,self.catalogue,self.at)
  self.assertEqual(outcome['status'],'PUBLISHED')
  result=json.loads((fixture.a/'docs/unique-tasks.json').read_bytes());self.assertEqual(result['batches'][0]['status'],'awaiting_verification')
  self.assertEqual(json.loads((fixture.a/'coordination/assignments.json').read_bytes())['assignments'][self.f.batch]['status'],'active')
  def unavailable(observed):raise OSError('private unavailable')
  sync.progress_provider=unavailable;sync.publish(self.summary,self.catalogue,self.at)
  self.assertEqual(json.loads((fixture.a/'docs/unique-tasks.json').read_bytes())['batches'][0]['status'],'active')
  def advance(observed):
   fixture.run_git(fixture.b,'pull','--ff-only','origin','main')
   fixture.ledger['assignments'][self.f.batch]['updated_at']='2026-11-19T01:00:00Z'
   fixture.write_ledger(fixture.b);fixture.commit(fixture.b,'authority advance');fixture.run_git(fixture.b,'push','origin','main')
   return self.progress()
  sync.progress_provider=advance
  with self.assertRaisesRegex(ValueError,'authority changed'):sync.publish(self.summary,self.catalogue,self.at)

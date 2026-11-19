"""Private adapter fixtures only; no remote or GitHub service."""
import contextlib,io,json,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from coordination.task_manager import write
from coordination.github_private import PrivateCatalogue
import test_github_private as fixtures
from coordination.github_task_manager import Manager, parser, dispatch, bounded_json

class ManagerTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.PrivateCatalogueTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  old=self.fixture.catalogue;parent=self.fixture.hub.root/'unique-work';parent.mkdir();root=parent/'generation';old.root.rename(root)
  self.catalogue=PrivateCatalogue(root,self.fixture.hub,self.fixture.generation);self.batch=self.fixture.batch_id
  self.config=dict(schema='kuina-private-github-authority-v1',queue_root=str(root),generation=self.fixture.generation,repo='wangseann/kuina-data-viewer')
  write(self.fixture.hub.root/'github-assignment-authority.json',self.config);self.manager=Manager(self.fixture.hub.root)
 def preparation(self):
  self.catalogue.fence_legacy_starts();return self.manager.prepare_work(self.batch,'seann',42)
 def working(self):
  prep=self.preparation();auth=dict(schema='kuina-github-working-authorization-v1',batch_id=self.batch,person='seann',assignment_issue=42,proof_sha256=prep['proof_sha256'],ledger_sha='a'*40,working_request_issue=43)
  self.manager.authorize(auth);return prep,self.manager.claim(prep['proof_sha256'])
 def test_no_actual_start_without_observed_permit(self):
  prep=self.preparation()
  with self.assertRaises((ValueError,FileNotFoundError)):self.manager.claim(prep['proof_sha256'])
  self.assertFalse((self.fixture.hub.root/'work-claims'/self.batch).exists())
 def test_preparation_url_closed_public_payload(self):
  result=self.preparation();query=parse_qs(urlsplit(result['github_start_url']).query)
  self.assertEqual(query['title'],['[Kuina start] '+self.batch]);body=query['body'][0]
  payload=json.loads(body.split('\n')[1]);self.assertEqual(set(payload),{'version','action','task_id','person','assignment_issue','proof_sha256'})
  self.assertEqual(payload['action'],'working');self.assertNotIn('uid',json.dumps(result));self.assertNotIn(str(self.fixture.base),json.dumps(result))
 def test_config_generation_path_and_closed_fields(self):
  for key,value in [('generation','0'*64),('queue_root',str(self.fixture.base)),('repo','other/repo'),('unknown',1)]:
   config=dict(self.config);config[key]=value;write(self.fixture.hub.root/'github-assignment-authority.json',config)
   with self.subTest(key=key),self.assertRaises((ValueError,FileNotFoundError)):self.manager.catalogue()
  write(self.fixture.hub.root/'github-assignment-authority.json',self.config);path=self.fixture.hub.root/'github-assignment-authority.json';other=path.with_suffix('.saved');path.rename(other);path.symlink_to(other)
  with self.assertRaises(ValueError):self.manager.catalogue()
 def test_guard_four_arguments_binds_work_token(self):
  prep=self.preparation();record=dict(batch_id=self.batch,person='seann',author='seann',assignment_issue=42,status='assigned',definition_sha256=self.catalogue.row(self.batch)['file']['sha256'],catalogue_generation=self.fixture.generation,created_at='2026-01-01T00:00:00Z',updated_at='2026-01-01T00:00:00Z',origin='github',work_proof_sha256=None,working_request_issue=None)
  result=self.manager.guard(self.batch,'working',record,prep['proof_sha256']);self.assertEqual(result['proof_sha256'],prep['proof_sha256'])
  with patch.object(PrivateCatalogue,'guard',return_value=result)as guard:self.manager.guard(self.batch,'working',record,prep['proof_sha256']);self.assertEqual(guard.call_args.args,(self.batch,'working',record,prep['proof_sha256']))
  for key,value in [('person','emily'),('catalogue_generation','0'*64),('definition_sha256','0'*64)]:
   changed=dict(record);changed[key]=value
   with self.assertRaises(ValueError):self.manager.guard(self.batch,'working',changed,prep['proof_sha256'])
 def test_actual_owner_reports_and_completion_is_final(self):
  prep,owner=self.working();self.assertEqual(self.manager.show(self.batch)['status'],'active')
  self.manager.report(self.batch,'seann','in_progress','Private progress');self.manager.report(self.batch,'seann','blocked','Private issue')
  self.assertEqual(self.manager.show(self.batch)['status'],'blocked')
  self.manager.report(self.batch,'seann','completed','Ready for independent review')
  self.assertEqual(self.manager.show(self.batch)['status'],'awaiting_verification')
  with self.assertRaises(ValueError):self.manager.report(self.batch,'seann','in_progress','Cannot reopen')
  self.assertEqual(self.manager.read_batch(self.batch)['targets'][0]['series_ids'],['original-private-series'])
 def test_other_uid_person_and_corrupt_owner_rejected(self):
  prep,owner=self.working()
  with patch('coordination.github_task_manager.os.getuid',return_value=os.getuid()+1):
   with self.assertRaises(ValueError):self.manager.report(self.batch,'seann','blocked','No')
  with self.assertRaises(ValueError):self.manager.report(self.batch,'emily','blocked','No')
  path=self.fixture.hub.root/'work-claims'/self.batch/'owner.json';record=json.loads(path.read_text());record['extra']='bad';write(path,record)
  with self.assertRaises(ValueError):self.manager.show(self.batch)
 def test_report_failure_leaves_unknown_lock_and_no_repeated_write(self):
  self.working()
  with patch('coordination.github_task_manager.exclusive_write',side_effect=OSError('synthetic failure')):
   with self.assertRaises(OSError):self.manager.report(self.batch,'seann','blocked','Interrupted')
  lock=self.fixture.hub.root/'work-claims'/self.batch/'.report-lock';self.assertTrue(lock.exists())
  with self.assertRaises(ValueError):self.manager.show(self.batch)
  with self.assertRaises(ValueError):self.manager.report(self.batch,'seann','blocked','Do not retry')
 def test_legacy_existing_worker_report_unchanged_no_config_needed(self):
  self.fixture.hub.claim('old-task','juan');(self.fixture.hub.root/'github-assignment-authority.json').unlink()
  self.manager.report('old-task','juan','in_progress','Original worker continues')
  self.assertEqual(self.manager.show('old-task')['assignee'],'juan')
  with patch.object(self.manager.legacy,'read_batch',return_value={'private':'legacy'})as read:self.assertEqual(self.manager.read_batch('old-task'),{'private':'legacy'});read.assert_called_once_with('old-task')
 def test_missing_private_proof_is_not_availability_or_reassignment(self):
  prep,_=self.working();self.manager.protocol().preparation_path(prep['proof_sha256']).unlink()
  with self.assertRaises(FileNotFoundError):self.manager.show(self.batch)
  self.assertTrue((self.fixture.hub.root/'work-claims'/self.batch).exists())
 def test_cli_does_not_offer_legacy_assign_or_claim_bypass(self):
  p=parser()
  for args in [['--hub',str(self.fixture.hub.root),'assign','old-task'],['--hub',str(self.fixture.hub.root),'claim','old-task','--person','juan']]:
   with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):p.parse_args(args)
  args=p.parse_args(['--hub',str(self.fixture.hub.root),'show','old-task']);self.assertEqual(dispatch(args)['id'],'old-task')
 def test_missing_authority_config_creates_no_directories(self):
  p=self.fixture.hub.root/'github-assignment-authority.json';p.unlink();before={str(f)for f in self.fixture.hub.root.rglob('*')}
  with self.assertRaises(FileNotFoundError):self.manager.prepare_work(self.batch,'seann',42)
  self.assertEqual(before,{str(f)for f in self.fixture.hub.root.rglob('*')})
 def test_json_arguments_closed_duplicate_and_size_rejection(self):
  for raw in ['[]','{"x":1,"x":2}','{"x":"'+'x'*16384+'"}']:
   with self.subTest(raw=raw[:30]),self.assertRaises(ValueError):bounded_json(raw)
 def test_permit_hash_and_unknown_journal_rejected(self):
  prep,_=self.working();directory=self.fixture.hub.root/'work-claims'/self.batch
  path=directory/'owner.json';value=json.loads(path.read_text());value['authorization_sha256']='0'*64;write(path,value)
  with self.assertRaises(ValueError):self.manager.report(self.batch,'seann','blocked','Bad proof')
  self.assertFalse((directory/'.report-lock').exists())
 def test_real_standalone_cli_private_scope_no_side_effects(self):
  command=Path(__file__).resolve().parents[1]/'coordination/github_task_manager.py'
  result=subprocess.run([sys.executable,'-B',str(command),'--hub',str(self.fixture.hub.root),'read-batch',self.batch],capture_output=True,timeout=30)
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['id'],self.batch)
  self.assertFalse((self.fixture.hub.root/'work-claims'/self.batch).exists())

if __name__=='__main__':unittest.main()

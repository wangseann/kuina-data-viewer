"""Protected legacy reservation continuation; no real API/private writes."""
import copy,threading,unittest
from coordination.github_claims import NativeFailure
from tests.test_github_assignments import AtomicGitHub,catalogue,guard,migration,imported,B,H,G,P,NOW
try:
 from coordination.github_assignments_v2 import Assignments
except ImportError:Assignments=None

class ImportedResumeTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Assignments,'Explicit protected resume not implemented')
  self.gh=AtomicGitHub();self.store=self.make();r=imported('assigned');r.update(author='alice',assignment_issue=7)
  self.store.initialize(migration([r]));self.original=copy.deepcopy(r)
 def make(self,**kw):return Assignments(self.gh,kw.pop('catalogue',catalogue),kw.pop('private_guard',guard),clock=lambda:NOW,**kw)
 def resume(self,**kw):
  args=dict(batch_id=B,person='seann',assignment_issue=7,proof_sha256=P,author='alice',request_issue=8);args.update(kw);return self.store.resume_imported(**args)
 def test_exact_resume_observed_and_old_fields_preserved(self):
  result=self.resume();self.assertEqual(result['status'],'started');r=self.store.snapshot()['ledger']['assignments'][B]
  self.assertEqual(r['origin'],'migration');self.assertEqual(r['status'],'active');self.assertEqual(r['work_proof_sha256'],P);self.assertEqual(r['working_request_issue'],8)
  for key in ('author','assignment_issue','created_at','person','definition_sha256','catalogue_generation'):self.assertEqual(r[key],self.original[key])
  self.assertEqual(self.store.release(B,'seann','alice',9,7)['status'],'rejected')
 def test_issue_idempotent_before_protected_rejection_even_privateproof_lost(self):
  self.resume();puts=self.gh.puts;self.store.private_guard=None;self.assertEqual(self.resume()['status'],'started');self.assertEqual(self.gh.puts,puts)
  for kw in [dict(person='emily'),dict(author='bob'),dict(assignment_issue=6),dict(proof_sha256=H)]:
   with self.subTest(kw=kw),self.assertRaises(NativeFailure):self.resume(**kw)
 def test_definition_generation_author_issue_must_match(self):
  for key,value in [('generation',P),('definition_sha256',P)]:
   s=self.make(catalogue=lambda batch:dict(catalogue(batch),**{key:value}))
   with self.assertRaises(NativeFailure):s.resume_imported(B,'seann',7,P,'alice',8)
  for kw in [dict(author='owner'),dict(assignment_issue=4),dict(person='emily')]:
   with self.assertRaises(NativeFailure):self.resume(**kw)
 def test_disabled_legacy_catalogue_allows_only_explicit_resume(self):
  self.store.catalogue=lambda batch:dict(catalogue(batch),assignment_enabled=False)
  with self.assertRaises(NativeFailure):self.store.set_working(B,'seann',7,P,author='alice',request_issue=8)
  self.assertEqual(self.resume()['status'],'started')
 def test_real_worker_unknown_proof_or_missing_original_metadata_hold(self):
  for state,proof in [('working',P),('unknown',None),('clear',H)]:
   s=self.make(private_guard=lambda *args:dict(schema='kuina-assignment-guard-v1',state=state,proof_sha256=proof))
   with self.subTest(state=state,proof=proof),self.assertRaises(NativeFailure):s.resume_imported(B,'seann',7,P,'alice',8)
  for key in ('author','assignment_issue'):
   gh=AtomicGitHub();s=Assignments(gh,catalogue,guard,clock=lambda:NOW);r=copy.deepcopy(self.original);r[key]=None;s.initialize(migration([r]))
   with self.assertRaises(NativeFailure):s.resume_imported(B,'seann',7,P,'alice',8)
 def test_lost_ack_single_resume_write(self):
  puts=self.gh.puts;self.gh.lose_ack=True;self.assertEqual(self.resume()['status'],'started');self.assertEqual(self.gh.puts,puts+1)
 def test_real_cas_race_release_cannot_make_import_available(self):
  self.gh.barrier=threading.Barrier(2);self.gh.barrier_left=2;errors=[]
  def resume():
   try:self.make().resume_imported(B,'seann',7,P,'alice',8)
   except Exception as e:errors.append(e)
  def release():
   try:self.make().release(B,'seann','alice',9,7)
   except Exception as e:errors.append(e)
  threads=[threading.Thread(target=resume),threading.Thread(target=release)]
  for t in threads:t.start()
  for t in threads:t.join(10)
  self.assertFalse(errors);r=self.store.snapshot()['ledger']['assignments'][B];self.assertEqual(r['origin'],'migration');self.assertEqual(r['status'],'active')
 def test_normal_github_assignments_cannot_use_legacy_resume(self):
  gh=AtomicGitHub();s=Assignments(gh,catalogue,guard,clock=lambda:NOW);s.initialize(migration());s.assign(B,'seann',7,'alice')
  with self.assertRaises(NativeFailure):s.resume_imported(B,'seann',7,P,'alice',8)

if __name__=='__main__':unittest.main()

"""Atomic fake Contents server: real threaded CAS, no GitHub/network calls."""
import base64,copy,hashlib,json,threading,unittest
from coordination.github_claims import NativeFailure
try:
 from coordination.github_assignments import Assignments,InvalidAssignment
except ImportError:
 Assignments=None;InvalidAssignment=ValueError

H='a'*64;G='b'*64;P='c'*64;NOW='2026-11-19T00:00:00+00:00';B='unique-stocks-prices-review-0123456789abcdef-000001'

def migration(records=None):return dict(schema='kuina-assignment-migration-v1',complete=True,source_sha256=H,catalogue_generation=G,records=records or [],receipts=[])
def imported(status='active'):
 return dict(batch_id=B,person='seann',author=None,assignment_issue=None,status=status,definition_sha256=H,catalogue_generation=G,created_at=NOW,updated_at=NOW,origin='migration',work_proof_sha256=None,working_request_issue=None)

def catalogue(batch):return dict(schema='kuina-assignment-catalogue-v1',batch_id=batch,generation=G,definition_sha256=H,assignment_enabled=True)
def guard(batch,action,record,proof=None):return dict(schema='kuina-assignment-guard-v1',state='clear',proof_sha256=proof or P)

class HTTPError(RuntimeError):
 def __init__(self,status):self.status=status

class AtomicGitHub:
 repo='owner/repo';owner='owner'
 def __init__(self):self.raw=None;self.sha=None;self.lock=threading.Lock();self.puts=0;self.gets=0;self.lose_ack=False;self.conflict=False;self.barrier=None;self.barrier_left=0;self.hide_once=False
 def api(self,path,method='GET',fields=None):
  if method=='GET':
   with self.lock:
    self.gets+=1
    if self.hide_once:self.hide_once=False;raise HTTPError(503)
    if self.raw is None:raise HTTPError(404)
    result=dict(type='file',size=len(self.raw),encoding='base64',content=base64.b64encode(self.raw).decode(),sha=self.sha)
    barrier=self.barrier if self.barrier_left else None
    if barrier:self.barrier_left-=1
   if barrier:barrier.wait(timeout=5)
   return result
  if method!='PUT':raise AssertionError('Unexpected mutation')
  with self.lock:
   if self.conflict or fields.get('sha')!=self.sha:raise HTTPError(409)
   raw=base64.b64decode(fields['content']);self.raw=raw;self.sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();self.puts+=1
   if self.lose_ack:self.lose_ack=False;raise TimeoutError('lost ACK')
   return dict(content=dict(sha=self.sha))

class AssignmentTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Assignments,'Assignment ledger not implemented');self.github=AtomicGitHub();self.store=self.make();self.store.initialize(migration())
 def make(self,**kw):return Assignments(self.github,kw.pop('catalogue',catalogue),kw.pop('private_guard',guard),clock=lambda:NOW,**kw)
 def test_threaded_cas_one_winner_and_immutable_loser_receipt(self):
  self.github.barrier=threading.Barrier(2);self.github.barrier_left=2;results=[];errors=[]
  def claim(person,issue,author):
   try:results.append(self.make().assign(B,person,issue,author))
   except Exception as e:errors.append(e)
  threads=[threading.Thread(target=claim,args=('seann',1,'alice')),threading.Thread(target=claim,args=('emily',2,'bob'))]
  for t in threads:t.start()
  for t in threads:t.join(10)
  self.assertFalse(errors);self.assertEqual(sorted(x['status']for x in results),['confirmed','rejected']);self.assertIn(self.store.status(B)['assignee'],('seann','emily'));self.assertEqual(len(self.store.snapshot()['ledger']['receipts']),2)
 def test_lost_ack_reconciles_one_write(self):
  before=self.github.puts;self.github.lose_ack=True;r=self.store.assign(B,'seann',1,'alice');self.assertEqual(r['status'],'confirmed');self.assertEqual(self.github.puts,before+1)
  self.assertEqual(self.store.request_status(B,1,action='assign',person='seann',author='alice')['status'],'confirmed')
 def test_no_confirmation_until_get_observes_receipt(self):
  original=self.github.api
  def api(path,method='GET',fields=None):
   value=original(path,method,fields)
   if method=='PUT':self.github.hide_once=True
   return value
  self.github.api=api
  with self.assertRaises(NativeFailure):self.store.assign(B,'seann',1,'alice')
  self.github.api=original;self.assertEqual(self.store.request_status(B,1)['status'],'confirmed')
 def test_stale_release_cannot_release_later_assignment(self):
  self.store.assign(B,'seann',1,'alice');self.store.release(B,'seann','alice',2,1)
  self.store.assign(B,'emily',3,'bob');r=self.store.release(B,'seann','alice',4,1)
  self.assertEqual(r['status'],'rejected');self.assertEqual(self.store.status(B)['assignment_issue'],3)
 def test_issue_replay_action_person_author_and_batch_bound(self):
  self.store.assign(B,'seann',1,'Alice');puts=self.github.puts;self.store.assign(B,'seann',1,'ALICE');self.assertEqual(self.github.puts,puts)
  for call in [lambda:self.store.assign(B,'emily',1,'alice'),lambda:self.store.assign(B,'seann',1,'bob'),lambda:self.store.assign('other-batch','seann',1,'alice'),lambda:self.store.release(B,'seann','alice',1,1)]:
   with self.assertRaises(NativeFailure):call()
 def test_unknown_schema_and_private_keys_rejected_before_publish(self):
  other=AtomicGitHub();s=Assignments(other,catalogue,guard)
  for bad in [dict(migration(),uid=11198),dict(migration(),schema='unknown'),dict(migration(),complete=False)]:
   with self.assertRaises((ValueError,NativeFailure)):s.initialize(bad)
  self.assertEqual(other.puts,0)
  doc=json.loads(self.github.raw);doc['context']='/private/path';self.github.raw=json.dumps(doc).encode();self.github.sha=hashlib.sha1(b'blob '+str(len(self.github.raw)).encode()+b'\0'+self.github.raw).hexdigest()
  with self.assertRaises(NativeFailure):self.store.status(B)
 def test_imported_active_and_reservation_protected_without_private_proof(self):
  for status in ('active','assigned'):
   gh=AtomicGitHub();s=Assignments(gh,catalogue,guard,clock=lambda:NOW);s.initialize(migration([imported(status)]));s.private_guard=None
   self.assertNotEqual(s.status(B)['status'],'available')
   r=s.release(B,'seann','owner',5,1,coordinator=True);self.assertEqual(r['status'],'rejected');self.assertIsNotNone(s.snapshot()['ledger']['assignments'].get(B))
 def test_missing_catalogue_guard_or_migration_never_available(self):
  s=Assignments(AtomicGitHub(),catalogue,guard)
  with self.assertRaises(NativeFailure):s.status(B)
  for kwargs in [dict(catalogue=None),dict(private_guard=None),dict(private_guard=lambda *a:dict(schema='kuina-assignment-guard-v1',state='unknown',proof_sha256=None))]:
   s=self.make(**kwargs);self.assertNotEqual(s.status(B)['status'],'available')
   with self.assertRaises(NativeFailure):s.assign(B,'seann',10,'alice')
 def test_bounded_cas_retries_and_payload(self):
  before_gets=self.github.gets;self.github.conflict=True
  with self.assertRaises(NativeFailure):self.make(max_attempts=2).assign(B,'seann',1,'alice')
  self.assertLessEqual(self.github.gets-before_gets,4)
  gh=AtomicGitHub();s=Assignments(gh,catalogue,guard,max_bytes=1024,clock=lambda:NOW);s.initialize(migration());before=gh.puts
  with self.assertRaises(NativeFailure):
   for i in range(1,20):s.assign(B,'seann',i,'alice')
  self.assertLess(gh.puts,before+20)
 def test_working_survives_missing_private_proof_and_blocks_release(self):
  self.store.assign(B,'seann',1,'alice');self.store.set_working(B,'seann',1,P,author='alice',request_issue=2)
  self.store.private_guard=None;self.assertEqual(self.store.status(B)['status'],'active');r=self.store.release(B,'seann','alice',3,1);self.assertEqual(r['status'],'rejected')
  self.assertEqual(self.store.request_status(B,2)['status'],'started')
 def test_working_guard_receives_exact_requested_proof(self):
  self.store.assign(B,'seann',1,'alice');seen=[]
  def check(batch,action,record,proof):seen.append(proof);return dict(schema='kuina-assignment-guard-v1',state='clear',proof_sha256=H)
  self.store.private_guard=check
  with self.assertRaises(NativeFailure):self.store.set_working(B,'seann',1,P)
  self.assertEqual(seen,[P]);self.assertEqual(self.store.snapshot()['ledger']['assignments'][B]['status'],'assigned')
 def test_coordinator_flag_not_authorization_and_catalogue_drift_blocks(self):
  self.store.assign(B,'seann',1,'alice');r=self.store.release(B,'seann','mallory',2,1,coordinator=True);self.assertEqual(r['status'],'rejected')
  self.store.catalogue=lambda batch:dict(catalogue(batch),definition_sha256=P)
  self.assertEqual(self.store.status(B)['status'],'blocked');self.assertEqual(self.store.status(B)['assignee'],'seann')
  with self.assertRaises(NativeFailure):self.store.release(B,'seann','alice',3,1)
 def test_initialize_never_overwrites_existing_authority(self):
  puts=self.github.puts;self.store.initialize(migration());self.assertEqual(self.github.puts,puts)
  with self.assertRaises(NativeFailure):self.store.initialize(dict(migration(),source_sha256=P))
 def test_work_start_vs_release_atomic_no_released_work(self):
  self.store.assign(B,'seann',1,'alice');self.github.barrier=threading.Barrier(2);self.github.barrier_left=2;errors=[]
  def start():
   try:self.make().set_working(B,'seann',1,P,author='alice',request_issue=2)
   except NativeFailure:pass
   except Exception as e:errors.append(e)
  def release():
   try:self.make().release(B,'seann','alice',3,1)
   except Exception as e:errors.append(e)
  ts=[threading.Thread(target=start),threading.Thread(target=release)]
  for t in ts:t.start()
  for t in ts:t.join(10)
  self.assertFalse(errors);ledger=self.store.snapshot()['ledger'];start_receipt=ledger['receipts'].get('2')
  if start_receipt and start_receipt['status']=='started':self.assertEqual(ledger['assignments'][B]['status'],'active')

if __name__=='__main__':unittest.main()

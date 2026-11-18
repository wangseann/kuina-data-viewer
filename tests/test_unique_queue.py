"""Unique repair claims fence the real, unchanged legacy Hub."""
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coordination.task_manager import Hub, digest, read, write
from coordination.unique_queue import UniqueQueue


def claim_race(root, legacy, batch, start, result):
    queue = UniqueQueue(root, Hub(legacy))
    start.wait(5)
    try:
        queue.claim(batch, 'juan')
        result.put(True)
    except (ValueError, OSError):
        result.put(False)


def old_claim_race(legacy, start, result):
    start.wait(5)
    try:
        Hub(legacy).claim('old-task', 'emily')
        result.put(True)
    except (ValueError, OSError):
        result.put(False)


class UniqueQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.hub = Hub(self.base/'legacy')
        self.hub.init()
        at = '2026-01-01T00:00:00+00:00'
        self.task = dict(id='old-task', category='stocks', kind='triage', assignee='juan',
                         effort=1, affected_series=5, issues=[], created_at=at, scope=None)
        write(self.hub.root/'tasks/old-task.json', self.task)
        self.hub.enable_self_service()
        self.input = self.base/'input'
        self.input.mkdir()
        self.manifest = dict(schema='kuina-unique-queue-v1', batches=[])
        self.add_batch('new-a', 'target-a', ['a','b'])
        self.add_batch('new-b', 'target-b', ['c','d','e'])
        self.queue_root = self.base/'queue'

    def add_batch(self, name, target, series):
        body = dict(schema='kuina-unique-batch-v1', id=name, targets=[dict(
            target_id=target, legacy_tasks=[dict(id=self.task['id'],task_sha256=digest(self.task))], series_ids=series)])
        raw = json.dumps(body).encode()
        (self.input/(name+'.json')).write_bytes(raw)
        self.manifest['batches'].append(dict(id=name, category='stocks', target_count=1,
            series_count=len(series), file=dict(path=name+'.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())))

    def install(self):
        path = self.input/'manifest.json'
        path.write_text(json.dumps(self.manifest))
        queue = UniqueQueue(self.queue_root, self.hub)
        queue.install(path)
        return queue

    def test_read_show_private_and_fresh_install(self):
        queue=self.install()
        self.assertEqual(queue.read('new-a')['targets'][0]['series_ids'],['a','b'])
        self.assertEqual(queue.show('new-a')['status'],'available')
        self.assertEqual(queue.show('new-a')['target_count'],1)
        self.assertFalse((self.hub.root/'task-locks/old-task').exists())
        with self.assertRaises((ValueError,FileExistsError)): queue.install(self.input/'manifest.json')

    def test_disjoint_new_batches_share_our_legacy_fence(self):
        queue=self.install()
        first=queue.claim('new-a','juan')
        self.assertEqual(first['uid'],os.getuid())
        queue.claim('new-b','emily')
        self.assertEqual(queue.show('new-b')['assignee'],'emily')
        with self.assertRaises(FileExistsError): self.hub.claim('old-task','juan')

    def test_duplicate_claim_never_repeats(self):
        queue=self.install();queue.claim('new-a','juan')
        before=(self.queue_root/'claims/new-a/owner.json').read_bytes()
        with self.assertRaises((ValueError,FileExistsError)):queue.claim('new-a','juan')
        self.assertEqual(before,(self.queue_root/'claims/new-a/owner.json').read_bytes())

    def test_unknown_legacy_lock_is_never_stolen(self):
        queue=self.install();lock=self.hub.root/'task-locks/old-task';lock.mkdir()
        with self.assertRaises((ValueError,FileExistsError)):queue.claim('new-a','juan')
        self.assertEqual(list(lock.iterdir()),[])
        self.assertFalse((self.queue_root/'claims/new-a').exists())

    def test_legacy_actual_claim_same_or_other_person_blocks_and_reports_continue(self):
        for person in ['juan','emily']:
            with self.subTest(person=person):
                # Separate queue attempts share one real legacy claim.
                if not (self.hub.root/'work-claims/old-task').exists(): self.hub.claim('old-task','juan')
                queue = self.install() if not self.queue_root.exists() else UniqueQueue(self.queue_root,self.hub)
                before=(self.hub.root/'work-claims/old-task/owner.json').read_bytes()
                with self.assertRaisesRegex(ValueError,'continue legacy'):queue.claim('new-a',person)
                self.hub.report('old-task','juan','in_progress','Existing work continues')
                self.assertEqual(before,(self.hub.root/'work-claims/old-task/owner.json').read_bytes())
                self.assertFalse((self.hub.root/'task-locks/old-task').exists())

    def test_legacy_reservation_blocks_without_fencing_assignee(self):
        queue=self.install();self.hub.assign('old-task','juan',42,'volunteer')
        with self.assertRaisesRegex(ValueError,'continue legacy'):queue.claim('new-a','juan')
        self.hub.claim('old-task','juan')
        self.assertEqual(self.hub.show('old-task')['assignee'],'juan')

    def test_report_requires_actual_uid_person_and_completion_is_final(self):
        queue=self.install();queue.claim('new-a','juan')
        with self.assertRaises(ValueError):queue.report('new-a','emily','in_progress','wrong')
        with patch('coordination.unique_queue.os.getuid',return_value=os.getuid()+1):
            with self.assertRaises(ValueError):queue.report('new-a','juan','in_progress','wrong UID')
        queue.report('new-a','juan','blocked','Private note /private/path')
        self.assertEqual(queue.show('new-a')['status'],'blocked')
        queue.report('new-a','juan','completed','Plan ready for independent review')
        self.assertEqual(queue.show('new-a')['status'],'awaiting_verification')
        with self.assertRaises(ValueError):queue.report('new-a','juan','in_progress','reopen')
        with self.assertRaises(ValueError):queue.report('new-b','juan','completed','unclaimed')

    def test_duplicate_target_across_batches_rejected(self):
        self.add_batch('new-c','target-a',['f'])
        with self.assertRaisesRegex(ValueError,'target'):self.install()

    def test_duplicate_original_series_across_targets_rejected(self):
        self.add_batch('new-c','target-c',['a'])
        with self.assertRaisesRegex(ValueError,'series'):self.install()

    def test_hash_count_path_and_closed_schema_rejected(self):
        original=copy.deepcopy(self.manifest)
        changes=[lambda m:m['batches'][0]['file'].update(sha256='0'*64),
                 lambda m:m['batches'][0].update(target_count=2),
                 lambda m:m['batches'][0]['file'].update(path='../new-a.json'),
                 lambda m:m.update(private_extra='forbidden')]
        for change in changes:
            self.manifest=copy.deepcopy(original);change(self.manifest)
            with self.subTest(manifest=self.manifest):
                with self.assertRaises(ValueError):self.install()
        self.assertFalse(self.queue_root.exists())

    def test_symlink_and_batch_size_caps_rejected(self):
        (self.input/'alias.json').symlink_to(self.input/'new-a.json')
        self.manifest['batches'][0]['file']['path']='alias.json'
        with self.assertRaises(ValueError):self.install()
        self.manifest['batches'][0]['file']['path']='new-a.json'
        with patch('coordination.unique_queue.MAX_BATCH_BYTES',1):
            with self.assertRaises(ValueError):self.install()

    def test_batch_target_limit_does_not_limit_numeric_fields(self):
        body=json.loads((self.input/'new-a.json').read_text())
        body['targets'][0]['series_ids']=[f'field-{i}' for i in range(1500)]
        raw=json.dumps(body).encode();(self.input/'new-a.json').write_bytes(raw)
        self.manifest['batches'][0].update(series_count=1500,file=dict(path='new-a.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        queue=self.install()
        self.assertEqual(len(queue.read('new-a')['targets'][0]['series_ids']),1500)

    def test_task_hash_or_installed_batch_change_fails_closed(self):
        queue=self.install();changed=dict(self.task,affected_series=6)
        write(self.hub.root/'tasks/old-task.json',changed)
        with self.assertRaisesRegex(ValueError,'hash'):queue.claim('new-a','juan')
        self.assertFalse((self.queue_root/'claims/new-a').exists())

    def test_interrupted_mutex_or_report_lock_is_not_recovered(self):
        queue=self.install();(self.queue_root/'locks/global').mkdir()
        with self.assertRaises(ValueError):queue.show('new-a')
        with self.assertRaises(FileExistsError):queue.claim('new-a','juan')
        (self.queue_root/'locks/global').rmdir();queue.claim('new-a','juan')
        (self.queue_root/'claims/new-a/.report-lock').mkdir()
        with self.assertRaises((ValueError,FileExistsError)):queue.report('new-a','juan','blocked','wait')

    def test_forged_fence_token_is_refused(self):
        queue=self.install();queue.claim('new-a','juan')
        fence=self.hub.root/'task-locks/old-task/unique-fence.json'
        record=read(fence);record['manifest_sha256']='0'*64;write(fence,record)
        with self.assertRaisesRegex(ValueError,'fence'):queue.claim('new-b','emily')

    def test_unknown_person_and_invalid_status_rejected(self):
        queue=self.install()
        with self.assertRaises(ValueError):queue.claim('new-a','intruder')
        queue.claim('new-a','juan')
        with self.assertRaises(ValueError):queue.report('new-a','juan','verified','No self certification')

    def test_process_shared_claim_is_exclusive(self):
        queue=self.install()
        ctx=multiprocessing.get_context('fork');start=ctx.Event();result=ctx.Queue()
        workers=[ctx.Process(target=claim_race,args=(str(self.queue_root),str(self.hub.root),'new-a',start,result)) for _ in range(2)]
        for worker in workers:worker.start()
        start.set()
        for worker in workers:worker.join(10);self.assertEqual(worker.exitcode,0)
        self.assertEqual(sorted(result.get(timeout=2) for _ in workers),[False,True])
        self.assertEqual(queue.show('new-a')['status'],'active')

    def test_real_old_v3_and_unique_claim_race_never_both_win(self):
        self.install()
        ctx=multiprocessing.get_context('fork');start=ctx.Event();result=ctx.Queue()
        workers=[ctx.Process(target=claim_race,args=(str(self.queue_root),str(self.hub.root),'new-a',start,result)),
                 ctx.Process(target=old_claim_race,args=(str(self.hub.root),start,result))]
        for worker in workers:worker.start()
        start.set()
        for worker in workers:worker.join(10);self.assertEqual(worker.exitcode,0)
        self.assertEqual(sorted(result.get(timeout=2) for _ in workers),[False,True])

    def test_more_than_100_targets_rejected(self):
        body=json.loads((self.input/'new-a.json').read_text())
        body['targets']=[dict(body['targets'][0],target_id=f'target-{i}',series_ids=[f'new-{i}']) for i in range(101)]
        raw=json.dumps(body).encode();(self.input/'new-a.json').write_bytes(raw)
        self.manifest['batches'][0].update(target_count=101,series_count=101,
            file=dict(path='new-a.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        with self.assertRaisesRegex(ValueError,'target limit'):self.install()

    def test_private_claim_journal_write_failure_retains_both_locks(self):
        queue=self.install();queue.claim('new-a','juan')
        with patch('coordination.unique_queue.write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):queue.report('new-a','juan','blocked','disk failed')
        self.assertTrue((self.queue_root/'locks/global').is_dir())
        self.assertTrue((self.queue_root/'claims/new-a/.report-lock').is_dir())
        with self.assertRaises(FileExistsError):queue.claim('new-b','emily')

    def test_installed_batch_hash_and_claim_owner_edit_refused(self):
        queue=self.install();queue.claim('new-a','juan')
        owner=self.queue_root/'claims/new-a/owner.json'
        data=read(owner);data['batch_sha256']='0'*64;write(owner,data)
        with self.assertRaises(ValueError):queue.show('new-a')
        batch=self.queue_root/'package/new-b.json'
        batch.chmod(0o644);batch.write_bytes(batch.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash/size'):queue.read('new-b')

    def test_successful_unique_claim_preserves_every_legacy_record_byte(self):
        queue=self.install()
        before={str(path.relative_to(self.hub.root)):path.read_bytes()
                for directory in ('tasks','claims','work-claims','assignments','verified')
                for path in (self.hub.root/directory).rglob('*') if path.is_file()}
        queue.claim('new-a','juan')
        after={str(path.relative_to(self.hub.root)):path.read_bytes()
               for directory in ('tasks','claims','work-claims','assignments','verified')
               for path in (self.hub.root/directory).rglob('*') if path.is_file()}
        self.assertEqual(before,after)

    def test_different_queue_cannot_adopt_another_queue_fence(self):
        queue=self.install();queue.claim('new-a','juan')
        other=UniqueQueue(self.base/'other-queue',self.hub)
        other.install(self.input/'manifest.json')
        with self.assertRaisesRegex(ValueError,'fence'):other.claim('new-b','emily')

    def test_maximum_unicode_private_note_remains_readable(self):
        queue=self.install();queue.claim('new-a','juan')
        queue.report('new-a','juan','blocked','😀'*4000)
        self.assertEqual(queue.show('new-a')['status'],'blocked')

    def test_show_reports_real_legacy_claim_blocker_without_new_assignee(self):
        queue=self.install();self.hub.claim('old-task','emily')
        row=queue.show('new-a')
        self.assertEqual(row['status'],'blocked')
        self.assertIsNone(row['assignee'])
        self.assertEqual(row['legacy_blockers'],[dict(task_id='old-task',state='active',assignee='emily')])
        self.assertFalse((self.queue_root/'claims/new-a').exists())

    def test_show_reports_legacy_reservation_blocker(self):
        queue=self.install();self.hub.assign('old-task','juan',42,'volunteer')
        row=queue.show('new-a')
        self.assertEqual(row['status'],'blocked')
        self.assertIsNone(row['assignee'])
        self.assertEqual(row['legacy_blockers'],[dict(task_id='old-task',state='assigned',assignee='juan')])

    def test_show_checks_task_hash_and_unknown_lock_without_writes(self):
        queue=self.install();lock=self.hub.root/'task-locks/old-task';lock.mkdir()
        with self.assertRaises((ValueError,FileNotFoundError)):queue.show('new-a')
        self.assertEqual(list(lock.iterdir()),[])
        lock.rmdir();write(self.hub.root/'tasks/old-task.json',dict(self.task,affected_series=9))
        with self.assertRaisesRegex(ValueError,'hash'):queue.show('new-a')
        self.assertFalse((self.queue_root/'claims/new-a').exists())

    def test_show_reuses_our_fence_read_only_and_checks_claimed_invariants(self):
        queue=self.install();queue.claim('new-a','juan')
        fence=self.hub.root/'task-locks/old-task/unique-fence.json'
        before=fence.read_bytes()
        self.assertEqual(queue.show('new-b')['status'],'available')
        self.assertEqual(queue.show('new-b')['legacy_blockers'],[])
        self.assertEqual(queue.show('new-a')['status'],'active')
        self.assertEqual(before,fence.read_bytes())
        fence.unlink();fence.parent.rmdir()
        with self.assertRaisesRegex(ValueError,'fence'):queue.show('new-a')

    def test_nested_package_directories_allow_shared_traversal_under_umask077(self):
        row=self.manifest['batches'][0]
        (self.input/'nested').mkdir()
        (self.input/'new-a.json').rename(self.input/'nested/new-a.json')
        row['file']['path']='nested/new-a.json'
        previous=os.umask(0o077)
        try:queue=self.install()
        finally:os.umask(previous)
        for path in [self.queue_root,self.queue_root/'package',self.queue_root/'package/nested']:
            self.assertEqual(path.stat().st_mode & 0o777,0o755)
        self.assertEqual((self.queue_root/'package/nested/new-a.json').stat().st_mode & 0o777,0o444)
        self.assertEqual(queue.read('new-a')['id'],'new-a')

    def test_assign_receipts_are_idempotent_and_native_claim_honors_person(self):
        queue=self.install()
        self.assertTrue(hasattr(queue,'assign'),'UniqueQueue assignment API required')
        result=queue.assign('new-a','emily',42,'volunteer')
        self.assertEqual(result,dict(status='assigned',task_id='new-a',person='emily',issue=42))
        self.assertEqual(queue.assign('new-a','emily',42,'volunteer'),result)
        self.assertEqual(queue.assignment_status('new-a'),dict(task_id='new-a',status='assigned',assignee='emily',assignment_issue=42))
        with self.assertRaises(ValueError):queue.claim('new-a','juan')
        queue.claim('new-a','emily')
        with self.assertRaises(ValueError):queue.release_assignment('new-a','emily','volunteer')
        self.assertEqual(queue.request_status('new-a',42),dict(task_id='new-a',request_issue=42,action='assign',person='emily',status='confirmed'))

    def test_release_is_origin_author_only_and_receipts_do_not_resurrect(self):
        queue=self.install()
        self.assertTrue(hasattr(queue,'assign'),'UniqueQueue assignment API required')
        queue.assign('new-a','emily',42,'volunteer')
        with self.assertRaises(ValueError):queue.release_assignment('new-a','emily','other',True,43,42)
        queue.release_assignment('new-a','emily','volunteer',False,43,42)
        self.assertEqual(queue.assignment_status('new-a')['status'],'available')
        queue.assign('new-a','juan',44,'new-author')
        queue.release_assignment('new-a','emily','volunteer',False,43,42)
        self.assertEqual(queue.assignment_status('new-a')['assignee'],'juan')
        queue.assign('new-a','emily',42,'volunteer')
        self.assertEqual(queue.assignment_status('new-a')['assignee'],'juan')
        self.assertEqual(queue.request_status('new-a',43)['status'],'released')

    def test_assignment_preserves_legacy_gate_and_requires_coordinator_uid(self):
        queue=self.install()
        self.assertTrue(hasattr(queue,'assign'),'UniqueQueue assignment API required')
        with patch('coordination.unique_queue.os.getuid',return_value=os.getuid()+1):
            with self.assertRaises(ValueError):queue.assign('new-a','emily',42,'volunteer')
        self.hub.assign('old-task','juan',7,'legacy-author')
        with self.assertRaisesRegex(ValueError,'continue legacy'):queue.assign('new-a','emily',42,'volunteer')
        self.assertFalse((self.queue_root/'assignments/new-a.json').exists())

    def test_assign_reservation_fences_old_claim_and_other_unique_batches_still_work(self):
        queue=self.install()
        self.assertTrue(hasattr(queue,'assign'),'UniqueQueue assignment API required')
        queue.assign('new-a','emily',42,'volunteer')
        with self.assertRaises(FileExistsError):self.hub.claim('old-task','juan')
        queue.assign('new-b','juan',43,'other-author')
        queue.claim('new-b','juan')
        self.assertEqual(queue.show('new-a')['status'],'assigned')
        self.assertEqual(queue.show('new-b')['status'],'active')

    def test_reservation_missing_fence_and_changed_assignment_hash_fail_closed(self):
        queue=self.install();queue.assign('new-a','emily',42,'volunteer')
        fence=self.hub.root/'task-locks/old-task/unique-fence.json'
        fence.unlink();fence.parent.rmdir()
        with self.assertRaisesRegex(ValueError,'fence'):queue.show('new-a')
        record=read(self.queue_root/'assignments/new-a.json');record['batch_sha256']='0'*64
        write(self.queue_root/'assignments/new-a.json',record)
        with self.assertRaisesRegex(ValueError,'hash'):queue.assignment_status('new-a')

    def test_lost_assignment_ack_has_durable_receipt_and_no_repeated_write(self):
        queue=self.install()
        original=write
        def lost_ack(path,value):
            original(path,value)
            if path.parent.name=='assignments':raise OSError('lost acknowledgement')
        with patch('coordination.unique_queue.write',side_effect=lost_ack):
            with self.assertRaises(OSError):queue.assign('new-a','emily',42,'volunteer')
        self.assertEqual(queue.request_status('new-a',42)['status'],'confirmed')
        self.assertTrue((self.queue_root/'locks/global').exists())
        with self.assertRaises(FileExistsError):queue.assign('new-a','emily',42,'volunteer')

    def test_snapshot_manifest_reads_are_constant_and_worker_mutations_stay_fresh(self):
        import coordination.unique_queue as implementation
        for number in range(10):
            self.add_batch('extra-'+str(number),'extra-target-'+str(number),['extra-series-'+str(number)])
        queue=self.install();original=implementation.file_bytes;reads=[]
        def measured(path,*args,**kwargs):
            if Path(path)==self.queue_root/'package/manifest.json':reads.append(Path(path).stat().st_size)
            return original(path,*args,**kwargs)
        with patch('coordination.unique_queue.file_bytes',side_effect=measured):
            rows=queue.snapshot()
        self.assertEqual(len(rows),12)
        self.assertEqual(len(reads),2,'Complete snapshots must read the manifest twice, independently of batch count')
        queue.claim('new-a','juan')
        self.assertEqual(next(row for row in queue.snapshot() if row['id']=='new-a')['status'],'active')
        queue.report('new-a','juan','blocked','fresh private report')
        self.assertEqual(next(row for row in queue.snapshot() if row['id']=='new-a')['status'],'blocked')
        with self.assertRaises(ValueError):queue.claim('new-a','juan')

    def test_snapshot_fails_if_manifest_or_global_lock_changes_during_scan(self):
        queue=self.install();original=queue._show_row
        def interrupted(row,*args):
            result=original(row,*args)
            if row['id']=='new-b':(self.queue_root/'locks/global').mkdir()
            return result
        with patch.object(queue,'_show_row',side_effect=interrupted):
            with self.assertRaisesRegex(ValueError,'pending|interrupted'):queue.snapshot()
        (self.queue_root/'locks/global').rmdir()
        def changed(row,*args):
            result=original(row,*args)
            if row['id']=='new-b':
                manifest=self.queue_root/'package/manifest.json';manifest.chmod(0o644)
                manifest.write_bytes(manifest.read_bytes()+b' ')
            return result
        with patch.object(queue,'_show_row',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'manifest|changed'):queue.snapshot()

    def test_snapshot_rejects_batch_metadata_replaced_after_its_row_was_read(self):
        queue=self.install();original=queue._show_row
        def changed(row,*args):
            result=original(row,*args)
            if row['id']=='new-b':
                path=self.queue_root/'package/new-a.json';path.chmod(0o644)
                path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(queue,'_show_row',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'batch|changed'):queue.snapshot()

    def test_legacy_task_definition_reads_once_per_id_but_checks_every_target_pin(self):
        queue=self.install();data=queue.read('new-a');template=data['targets'][0]
        data['targets']=[dict(copy.deepcopy(template),target_id='target-'+str(number),
                             series_ids=['series-'+str(number)]) for number in range(100)]
        definition=self.hub.root/'tasks/old-task.json';before=definition.read_bytes()
        with patch.object(self.hub,'task',wraps=self.hub.task) as reader:
            tasks=queue.legacy_tasks(data)
            self.assertEqual(set(tasks),{'old-task'})
            self.assertEqual(tasks['old-task'],self.task)
            self.assertEqual(reader.call_count,1,'One immutable definition read per distinct ID, not per target')
        data['targets'][-1]['legacy_tasks'][0]['task_sha256']='0'*64
        with patch.object(self.hub,'task',wraps=self.hub.task) as reader:
            with self.assertRaisesRegex(ValueError,'legacy task hash mismatch'):queue.legacy_tasks(data)
            self.assertEqual(reader.call_count,1,'Conflicting later pins must fail against the same loaded definition')
        self.assertEqual(definition.read_bytes(),before)

    def test_legacy_task_definition_cache_does_not_survive_a_call(self):
        queue=self.install();data=queue.read('new-a')
        self.assertEqual(queue.legacy_tasks(data)['old-task'],self.task)
        write(self.hub.root/'tasks/old-task.json',dict(self.task,affected_series=6))
        with self.assertRaisesRegex(ValueError,'legacy task hash mismatch'):queue.legacy_tasks(data)

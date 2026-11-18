"""Private wrapper routes reviewed unique work and preserves old CLI contracts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coordination.task_manager import Hub, digest, write
from coordination.unique_queue import UniqueQueue
from coordination.unique_task_manager import Manager, main
import unique_dashboard


class UniqueManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.hub=Hub(self.base/'hub');self.hub.init()
        self.task=dict(id='legacy-task',category='stocks',kind='triage',assignee='juan',effort=1,
                       affected_series=1,issues=[],created_at='2026-01-01T00:00:00+00:00',scope=None)
        write(self.hub.root/'tasks/legacy-task.json',self.task);self.hub.enable_self_service()

    def manager(self):
        return Manager(self.hub.root)

    def enable(self):
        source=self.base/'input';source.mkdir()
        body=dict(schema='kuina-unique-batch-v1',id='unique-a',targets=[dict(target_id='target-a',
                  legacy_tasks=[dict(id='legacy-task',task_sha256=digest(self.task))],series_ids=['original-id'])])
        raw=json.dumps(body).encode();(source/'a.json').write_bytes(raw)
        manifest=dict(schema='kuina-unique-queue-v1',batches=[dict(id='unique-a',category='stocks',target_count=1,
                      series_count=1,file=dict(path='a.json',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))])
        path=source/'manifest.json';path.write_text(json.dumps(manifest))
        parent=self.hub.root/'unique-work';parent.mkdir()
        queue=UniqueQueue(parent/'generation1',self.hub);result=queue.install(path)
        write(self.hub.root/'unique-work.json',dict(schema_version=1,queue_root=str(queue.root),manifest_sha256=result['manifest_sha256']))
        return queue

    def test_no_pointer_preserves_legacy_show_list_claim_report(self):
        manager=self.manager()
        self.assertEqual(manager.show('legacy-task'),self.hub.show('legacy-task'))
        self.assertEqual(manager.listing(),self.hub.listing())
        manager.claim('legacy-task','juan');manager.report('legacy-task','juan','blocked','Old report unchanged')
        self.assertEqual(self.hub.show('legacy-task')['status'],'blocked')

    def test_enabled_pointer_routes_unique_and_keeps_legacy_continuity(self):
        self.enable();manager=self.manager()
        self.assertEqual([r['id'] for r in manager.listing()],['unique-a'])
        self.assertEqual({r['id'] for r in manager.listing(include_legacy=True)},{'unique-a','legacy-task'})
        self.assertEqual(manager.show('legacy-task'),self.hub.show('legacy-task'))
        self.assertEqual(manager.read_batch('unique-a')['targets'][0]['series_ids'],['original-id'])
        with patch.object(manager.legacy,'read_batch',return_value={'legacy':'unchanged'}) as reader:
            self.assertEqual(manager.read_batch('legacy-task'),{'legacy':'unchanged'});reader.assert_called_once_with('legacy-task')
        manager.assign('unique-a','emily',42,'volunteer')
        self.assertEqual(manager.assignment_status('unique-a')['assignee'],'emily')
        self.assertEqual(manager.request_status('unique-a',42)['status'],'confirmed')
        manager.claim('unique-a','emily');manager.report('unique-a','emily','blocked','PRIVATE NOTE /secret/path')
        self.assertEqual(manager.show('unique-a')['status'],'blocked')

    def test_pointer_closed_hash_path_and_symlink_guards(self):
        queue=self.enable();manager=self.manager()
        pointer=self.hub.root/'unique-work.json';original=json.loads(pointer.read_text())
        for mutation in [dict(original,manifest_sha256='0'*64),dict(original,queue_root=str(self.base)),dict(original,extra='bad')]:
            write(pointer,mutation)
            with self.subTest(pointer=mutation):
                with self.assertRaises(ValueError):manager.listing()
        write(pointer,original);pointer.unlink();pointer.symlink_to(queue.root/'queue.json')
        with self.assertRaises(ValueError):manager.listing()

    def test_public_snapshot_exact_dashboard_contract_and_privacy(self):
        self.enable();manager=self.manager();manager.assign('unique-a','emily',42,'volunteer')
        manager.claim('unique-a','emily');manager.report('unique-a','emily','blocked','PRIVATE NOTE /secret/path')
        tasks=manager.unique_snapshot()
        summary=dict(schema=unique_dashboard.SUMMARY_SCHEMA,generated_at=tasks['generated_at'],input_manifest_sha256='a'*64,
                     grouping_status='VERIFIED_WITHIN_DATASETS',categories=[dict(id='stocks',stored_numeric_series=1,
                     unique_work_targets=1,distinct_measurement_groups=1,targets_with_saved_eligible_fields=0,unresolved_identity_targets=0)])
        self.assertTrue(unique_dashboard.validate(summary,tasks))
        text=json.dumps(tasks)
        for private in ['PRIVATE NOTE','/secret/path',str(self.base),'uid','task_sha256','original-id','legacy-task','legacy_blockers']:
            self.assertNotIn(private,text)
        self.assertEqual(tasks['batches'][0]['assignment_issue'],42)

    def test_public_snapshot_legacy_blocker_sanitized_without_reassignment(self):
        self.enable();self.hub.assign('legacy-task','juan',42,'volunteer')
        tasks=self.manager().unique_snapshot();row=tasks['batches'][0]
        self.assertEqual(row['status'],'blocked');self.assertIsNone(row['assignee'])
        self.assertEqual(row['blocker_codes'],['legacy_reservation'])

    def test_cli_old_delegation_and_new_broker_commands(self):
        self.enable()
        def invoke(*args):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):main(['--hub',str(self.hub.root),*args])
            return json.loads(output.getvalue())
        self.assertEqual(invoke('show','legacy-task')['id'],'legacy-task')
        invoke('assign','unique-a','--person','emily','--issue','42','--github-author','volunteer')
        self.assertEqual(invoke('assignment-status','unique-a')['status'],'assigned')
        invoke('release-assignment','unique-a','--person','emily','--github-author','volunteer','--request-issue','43','--assignment-issue','42')
        self.assertEqual(invoke('request-status','unique-a','--issue','43')['status'],'released')
        output=self.base/'public.json'
        invoke('unique-snapshot','--output',str(output))
        self.assertEqual(json.loads(output.read_text())['schema'],unique_dashboard.TASK_SCHEMA)

    def test_pointer_requires_absolute_path_and_protected_ancestors(self):
        queue=self.enable();manager=self.manager();pointer=self.hub.root/'unique-work.json'
        original=json.loads(pointer.read_text())
        previous=os.getcwd()
        try:
            os.chdir(self.base)
            write(pointer,dict(original,queue_root='hub/unique-work/generation1'))
            with self.assertRaises(ValueError):manager.listing()
        finally:os.chdir(previous)
        write(pointer,original);queue.root.parent.chmod(0o777)
        with self.assertRaises(ValueError):manager.listing()

    def test_existing_github_broker_confirms_real_queue_requests(self):
        from types import SimpleNamespace
        from coordination.github_claims import process_issue
        self.enable();manager=self.manager()
        native=SimpleNamespace(status=manager.assignment_status,request_status=manager.request_status,
                               assign=manager.assign,release=lambda task,person,author,number,assignment,coordinator=False:
                               manager.release_assignment(task,person,author,coordinator,number,assignment))
        finished=[];github=SimpleNamespace(finish=lambda issue,result:finished.append(result))
        def issue(number,action,assignment=None):
            payload=dict(version=1,action=action,task_id='unique-a',person='emily')
            if assignment is not None:payload['assignment_issue']=assignment
            return dict(number=number,user={'login':'volunteer'},
                        title='[Kuina '+('claim' if action=='assign' else 'release')+'] unique-a',
                        body='<!-- kuina-request-v1\n'+json.dumps(payload)+'\n-->')
        assigned=process_issue(issue(42,'assign'),github,native,'owner')
        self.assertEqual(assigned['status'],'confirmed')
        self.assertEqual(manager.assignment_status('unique-a')['assignment_issue'],42)
        released=process_issue(issue(43,'release',42),github,native,'owner')
        self.assertEqual(released['status'],'released')
        manager.assign('unique-a','juan',44,'other-author')
        self.assertEqual(process_issue(issue(43,'release',42),github,native,'owner')['status'],'released')
        self.assertEqual(manager.assignment_status('unique-a')['assignee'],'juan')

    def test_corrupted_private_source_rejects_assignment_and_public_snapshot(self):
        queue=self.enable();manager=self.manager()
        batch=queue.root/'package/a.json';batch.chmod(0o644);batch.write_bytes(batch.read_bytes()+b' ')
        with self.assertRaises(ValueError):manager.assign('unique-a','emily',42,'volunteer')
        with self.assertRaises(ValueError):manager.unique_snapshot()
        self.assertFalse((queue.root/'assignments/unique-a.json').exists())

    def publication(self,queue):
        summary=dict(schema=unique_dashboard.SUMMARY_SCHEMA,generated_at='2026-11-18T00:00:00Z',
                     input_manifest_sha256='a'*64,grouping_status='VERIFIED_WITHIN_DATASETS',
                     categories=[dict(id='stocks',stored_numeric_series=1,unique_work_targets=1,
                     distinct_measurement_groups=1,targets_with_saved_eligible_fields=0,unresolved_identity_targets=0)])
        manifest=queue.configuration()[0]['manifest_sha256']
        write(queue.root/'publication.json',dict(schema='kuina-unique-publication-v1',manifest_sha256=manifest,summary=summary))
        return summary

    def test_publication_envelope_binds_summary_to_exact_queue_and_stays_sanitized(self):
        queue=self.enable();summary=self.publication(queue);manager=self.manager()
        manager.claim('unique-a','emily');manager.report('unique-a','emily','blocked','PRIVATE NOTE /secret/path')
        result=manager.publication_snapshot()
        self.assertEqual(set(result),{'queue_manifest_sha256','summary','tasks'})
        self.assertEqual(result['queue_manifest_sha256'],queue.configuration()[0]['manifest_sha256'])
        self.assertEqual(result['summary'],summary)
        self.assertTrue(unique_dashboard.validate(result['summary'],result['tasks']))
        for private in ('PRIVATE NOTE','/secret/path',str(self.base),'original-id','legacy-task'):
            self.assertNotIn(private,json.dumps(result))
        output=self.base/'publication-envelope.json';stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            main(['--hub',str(self.hub.root),'publication-snapshot','--output',str(output)])
        self.assertEqual(set(json.loads(output.read_text())),set(result))

    def test_publication_rejects_changed_pointer_hash_private_fields_and_mutable_record(self):
        queue=self.enable();self.publication(queue);manager=self.manager()
        path=queue.root/'publication.json';original=json.loads(path.read_text())
        for changed in (dict(original,manifest_sha256='0'*64),dict(original,private_path='/secret'),
                        dict(original,summary=dict(original['summary'],observations=[1]))):
            write(path,changed)
            with self.subTest(record=changed):
                with self.assertRaises(ValueError):manager.publication_snapshot()
        write(path,original);path.chmod(0o666)
        with self.assertRaises(ValueError):manager.publication_snapshot()
        path.chmod(0o644)
        real_snapshot=queue.snapshot
        def switch_pointer():
            result=real_snapshot()
            pointer=self.hub.root/'unique-work.json';data=json.loads(pointer.read_text())
            write(pointer,dict(data,manifest_sha256='0'*64))
            return result
        with patch.object(manager,'queue',return_value=queue),patch.object(queue,'snapshot',side_effect=switch_pointer):
            with self.assertRaisesRegex(ValueError,'pointer'):manager.publication_snapshot()

    def test_full_manager_snapshot_manifest_io_is_constant_for_many_batches(self):
        import coordination.unique_queue as core
        import coordination.unique_task_manager as wrapper
        first=self.enable();source=self.base/'input';manifest=json.loads((source/'manifest.json').read_text())
        original_body=json.loads((source/'a.json').read_text())
        for number in range(9):
            body=dict(original_body,id='unique-extra-'+str(number),targets=[dict(original_body['targets'][0],
                      target_id='extra-target-'+str(number),series_ids=['extra-series-'+str(number)])])
            raw=json.dumps(body).encode();name='extra-'+str(number)+'.json';(source/name).write_bytes(raw)
            manifest['batches'].append(dict(manifest['batches'][0],id=body['id'],
                file=dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())))
        (source/'manifest.json').write_text(json.dumps(manifest))
        queue=UniqueQueue(first.root.parent/'generation2',self.hub);installed=queue.install(source/'manifest.json')
        write(self.hub.root/'unique-work.json',dict(schema_version=1,queue_root=str(queue.root),manifest_sha256=installed['manifest_sha256']))
        reads=[];original=core.file_bytes
        def measured(path,*args,**kwargs):
            if Path(path)==queue.root/'package/manifest.json':reads.append(Path(path).stat().st_size)
            return original(path,*args,**kwargs)
        with patch.object(core,'file_bytes',side_effect=measured),patch.object(wrapper,'file_bytes',side_effect=measured):
            tasks=self.manager().unique_snapshot()
        self.assertEqual(len(tasks['batches']),10)
        self.assertEqual(len(reads),3,'Wrapper validation plus snapshot must perform constant manifest IO')

    def test_publication_initial_pointer_must_identify_the_exact_queue_used(self):
        queue=self.enable();self.publication(queue);manager=self.manager()
        pointer=self.hub.root/'unique-work.json';record=json.loads(pointer.read_text())
        write(pointer,dict(record,manifest_sha256='0'*64))
        # Model a pointer change between the initial read and queue selection.
        with patch.object(manager,'queue',return_value=queue):
            with self.assertRaisesRegex(ValueError,'pointer'):manager.publication_snapshot()

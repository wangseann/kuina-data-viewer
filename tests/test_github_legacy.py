"""Real Hub/500-record legacy scopes; no GitHub or backend calls."""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from coordination.task_manager import Hub, digest, write
from coordination.unique_queue import UniqueQueue
import test_task_batches
from coordination import github_legacy as bridge


class LegacyBridgeTests(unittest.TestCase):
    def setUp(self):
        fixture = test_task_batches.BatchTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.hub = Hub(fixture.hub.root.resolve())
        fixture.manifest = fixture.manifest.resolve()
        fixture.page = fixture.page.resolve()
        fixture.split()
        self.hub = fixture.hub
        self.hub.enable_self_service()
        self.tasks = fixture.children()
        self.task = self.tasks[0]
        self.batch = self.task['id']
        self.hub.assign(self.batch, 'seann', 42, 'Alice')
        source = fixture.root.resolve() / 'unique-input'
        source.mkdir()
        rows = []
        for i, task in enumerate(self.tasks):
            name = 'batch' + str(i) + '.json'
            value = dict(schema='kuina-unique-batch-v1', id='unique-bridge-' + str(i), targets=[dict(
                target_id='subject' + str(i), series_ids=['synthetic-series' + str(i)],
                legacy_tasks=[dict(id=task['id'], task_sha256=digest(task))])])
            raw = json.dumps(value).encode()
            (source / name).write_bytes(raw)
            rows.append(dict(id=value['id'], category='stocks', target_count=1, series_count=1,
                             file=dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())))
        raw = json.dumps(dict(schema='kuina-unique-queue-v1', batches=rows)).encode()
        (source / 'manifest.json').write_bytes(raw)
        queue = UniqueQueue(fixture.root.resolve() / 'queue', self.hub)
        queue.install(source / 'manifest.json')
        self.generation = hashlib.sha256(raw).hexdigest()
        self.catalogue = bridge.LegacyCatalogue(queue.root, self.hub, self.generation)
        self.catalogue.fence_legacy_starts()
        self.protocol = bridge.CombinedWorkProtocol(self.catalogue)
        current = self.hub.reservation(self.task)['current']
        self.assignment = dict(batch_id=self.batch, person='seann', author='alice', assignment_issue=42,
            status='assigned', definition_sha256=digest(self.task), catalogue_generation=self.generation,
            origin='migration', created_at=current['assigned_at'], updated_at=current['assigned_at'],
            work_proof_sha256=None, working_request_issue=None)

    def test_existing_legacy_reservation_has_definition_but_never_new_assignment(self):
        row = self.catalogue.row(self.batch)
        self.assertEqual(row['file']['sha256'], digest(self.task))
        self.assertEqual(row['category'], 'stocks')
        self.assertFalse(self.catalogue.catalogue(self.batch)['assignment_enabled'])
        self.assertEqual(self.hub.read_batch(self.batch)['selected'], 500)

    def preparation(self):
        return self.protocol.prepare(self.batch, 'seann', 42)

    def authorization(self, proof):
        return dict(schema='kuina-github-working-authorization-v1', batch_id=self.batch,
                    person='seann', assignment_issue=42, proof_sha256=proof['proof_sha256'],
                    ledger_sha='a' * 40, working_request_issue=43)

    def fences(self):
        return {str(p.relative_to(self.hub.root)): p.read_bytes()
                for p in (self.hub.root / 'task-locks').rglob('unique-fence.json')}

    def test_preparation_has_no_claim_and_needs_observed_permit(self):
        fences = self.fences()
        proof = self.preparation()
        self.assertEqual(set(proof), {'schema', 'batch_id', 'person', 'assignment_issue', 'proof_sha256'})
        self.assertNotIn(str(self.hub.root), json.dumps(proof))
        self.assertFalse((self.hub.root / 'work-claims' / self.batch).exists())
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.protocol.claim(proof['proof_sha256'])
        self.assertEqual(self.fences(), fences)

    def test_imported_working_guard_exact_original_binding_and_release_never_clear(self):
        proof = self.preparation()
        result = self.catalogue.guard(self.batch, 'working', self.assignment, proof['proof_sha256'])
        self.assertEqual(result['state'], 'clear')
        self.assertEqual(result['proof_sha256'], proof['proof_sha256'])
        for key, value in [('author', 'mallory'), ('person', 'emily'), ('assignment_issue', 41),
                           ('definition_sha256', '0' * 64), ('catalogue_generation', '0' * 64),
                           ('origin', 'github'), ('status', 'active')]:
            record = dict(self.assignment, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.catalogue.guard(self.batch, 'working', record, proof['proof_sha256'])
        self.assertNotEqual(self.catalogue.guard(self.batch, 'release', self.assignment)['state'], 'clear')

    def test_exact_old_worker_schema_native_report_and_permit_idempotency(self):
        proof = self.preparation()
        native_before = (self.hub.root / 'assignments' / (self.batch + '.json')).read_bytes()
        fences = self.fences()
        self.protocol.authorize(self.authorization(proof))
        owner = self.protocol.claim(proof['proof_sha256'])
        path = self.hub.root / 'work-claims' / self.batch
        self.assertEqual(set(owner), {'uid', 'person', 'task_sha256', 'claimed_at'})
        self.assertEqual({p.name for p in path.iterdir()}, {'owner.json'})
        self.assertEqual(self.hub.work_claim_record(self.task)[1], owner)
        self.assertEqual(self.hub.state(self.task)[0], 'active')
        self.hub.report(self.batch, 'seann', 'in_progress', 'Continue the original 500-record assignment')
        self.assertEqual(self.hub.state(self.task)[0], 'active')
        self.assertEqual(self.protocol.authorize(self.authorization(proof))['status'], 'already_authorized')
        self.assertEqual(self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])['uid'], os.getuid())
        with self.assertRaises((ValueError, FileExistsError)):
            self.protocol.claim(proof['proof_sha256'])
        with self.assertRaises(FileExistsError):
            self.hub.claim(self.batch, 'seann')
        self.assertEqual(self.hub.read_batch(self.batch)['selected'], 500)
        self.assertEqual((self.hub.root / 'assignments' / (self.batch + '.json')).read_bytes(), native_before)
        self.assertEqual(self.fences(), fences)

    def test_no_prepare_for_wrong_person_issue_or_existing_worker(self):
        for person, issue in [('emily', 42), ('seann', 41)]:
            with self.assertRaises(ValueError):
                self.protocol.prepare(self.batch, person, issue)
        proof = self.preparation()
        self.protocol.authorize(self.authorization(proof))
        self.protocol.claim(proof['proof_sha256'])
        with self.assertRaises(ValueError):
            self.preparation()

    def test_full_reservation_context_hash_prevents_author_same_issue_swap(self):
        proof = self.preparation()
        path = self.hub.root / 'assignments' / (self.batch + '.json')
        record = json.loads(path.read_bytes())
        record['current']['github_author'] = 'Mallory'
        write(path, record)
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])
        context = self.protocol.context_path(proof['proof_sha256'])
        value = json.loads(context.read_bytes())
        value['reservation']['github_author'] = 'Mallory'
        context.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])

    def test_wrong_uid_and_context_mode_rejected_before_worker(self):
        proof = self.preparation()
        self.protocol.authorize(self.authorization(proof))
        with patch('coordination.github_work.os.getuid', return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                self.protocol.claim(proof['proof_sha256'])
        path = self.protocol.context_path(proof['proof_sha256'])
        path.chmod(0o666)
        with self.assertRaises(ValueError):
            self.protocol.claim(proof['proof_sha256'])
        self.assertFalse((self.hub.root / 'work-claims' / self.batch).exists())

    def test_unknown_or_missing_target_fence_and_generation_fail_closed(self):
        proof = self.preparation()
        marker = self.hub.root / 'task-locks' / self.batch / 'unique-fence.json'
        value = json.loads(marker.read_bytes())
        value['manifest_sha256'] = '0' * 64
        write(marker, value)
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])
        self.assertTrue(marker.exists())

    def test_unique_preparation_and_claim_delegate_unchanged(self):
        batch = 'unique-bridge-1'
        proof = self.protocol.prepare(batch, 'emily', 77)
        authorization = dict(self.authorization(proof), batch_id=batch, person='emily', assignment_issue=77)
        self.protocol.authorize(authorization)
        owner = self.protocol.claim(proof['proof_sha256'])
        self.assertEqual(owner['schema'], 'kuina-github-private-worker-v1')
        self.assertEqual(owner['preparation_sha256'], proof['proof_sha256'])
        self.assertEqual(len(owner), 7)

    def test_legacy_without_current_reservation_or_worker_is_not_catalogued(self):
        with self.assertRaises(ValueError):
            self.catalogue.row(self.tasks[1]['id'])

    def test_missing_context_or_permit_never_creates_worker(self):
        proof = self.preparation()
        context = self.protocol.context_path(proof['proof_sha256'])
        context.unlink()
        with self.assertRaises(FileNotFoundError):
            self.protocol.claim(proof['proof_sha256'])
        self.assertFalse((self.hub.root / 'work-claims' / self.batch).exists())

    def test_preparation_mode_and_unknown_fence_fail_closed(self):
        proof = self.preparation()
        token = self.protocol.preparation_path(proof['proof_sha256'])
        token.chmod(0o666)
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])
        token.chmod(0o644)
        lock = self.hub.root / 'task-locks' / self.batch
        (lock / 'unknown').write_text('unrecognized lock state')
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])

    def test_wrong_permit_cannot_start_and_native_timestamp_is_pinned(self):
        proof = self.preparation()
        authorization = self.authorization(proof)
        authorization['proof_sha256'] = '0' * 64
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.protocol.authorize(authorization)
        path = self.hub.root / 'assignments' / (self.batch + '.json')
        record = json.loads(path.read_bytes())
        record['current']['assigned_at'] = '2020-01-01T00:00:00Z'
        write(path, record)
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])

    def test_late_reservation_change_leaves_no_worker_owner(self):
        proof = self.preparation()
        self.protocol.authorize(self.authorization(proof))
        original = self.protocol.current_context
        calls = []
        def changed_after_exclusive_directory(prepared, context):
            calls.append(1)
            if len(calls) == 3:
                path = self.hub.root / 'assignments' / (self.batch + '.json')
                record = json.loads(path.read_bytes())
                record['current']['github_author'] = 'Mallory'
                write(path, record)
            return original(prepared, context)
        with patch.object(self.protocol, 'current_context', side_effect=changed_after_exclusive_directory):
            with self.assertRaises(ValueError):
                self.protocol.claim(proof['proof_sha256'])
        path = self.hub.root / 'work-claims' / self.batch
        self.assertTrue(path.is_dir())  # Uncertain starts are retained, never retried or removed.
        self.assertFalse((path / 'owner.json').exists())

    def test_existing_worker_old_claim_time_does_not_verify(self):
        proof = self.preparation()
        self.protocol.authorize(self.authorization(proof))
        self.protocol.claim(proof['proof_sha256'])
        path = self.hub.root / 'work-claims' / self.batch / 'owner.json'
        owner = json.loads(path.read_bytes())
        owner['claimed_at'] = '2020-01-01T00:00:00Z'
        write(path, owner)
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'seann', 42, proof['proof_sha256'])
        self.assertEqual(self.catalogue.guard(self.batch, 'release', self.assignment)['state'], 'working')

    def test_missing_fence_is_never_created_by_resolution(self):
        marker = self.hub.root / 'task-locks' / self.batch / 'unique-fence.json'
        marker.unlink()
        marker.parent.rmdir()
        with self.assertRaises(ValueError):
            self.preparation()
        self.assertFalse(marker.parent.exists())
        # Only the deliberate migration operator may fence a known reservation.
        self.catalogue.queue.fence(self.task, self.catalogue.config)
        self.assertEqual(self.preparation()['person'], 'seann')

    def test_non_self_service_hub_cannot_prepare(self):
        (self.hub.root / 'self-service.json').unlink()
        self.catalogue.legacy = Hub(self.hub.root)
        protocol = bridge.CombinedWorkProtocol(self.catalogue)
        with self.assertRaises(ValueError):
            protocol.prepare(self.batch, 'seann', 42)


if __name__ == '__main__':
    unittest.main()

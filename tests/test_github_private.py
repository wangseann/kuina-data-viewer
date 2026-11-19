"""GitHub migration keeps private scopes and fences legacy starts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from coordination.task_manager import Hub, digest, write
from coordination.unique_queue import UniqueQueue
from coordination.github_private import PrivateCatalogue


class PrivateCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.hub = Hub(self.base / 'legacy')
        self.hub.init()
        self.task = dict(id='old-task', category='stocks', kind='triage', assignee='juan',
                         effort=1, affected_series=1, issues=[],
                         created_at='2026-01-01T00:00:00+00:00', scope=None)
        write(self.hub.root / 'tasks/old-task.json', self.task)
        self.hub.enable_self_service()
        source = self.base / 'input'
        source.mkdir()
        batch = dict(schema='kuina-unique-batch-v1', id='unique-test-000001', targets=[dict(
            target_id='subject', legacy_tasks=[dict(id='old-task', task_sha256=digest(self.task))],
            series_ids=['original-private-series'])])
        raw = json.dumps(batch).encode()
        (source / 'batch.json').write_bytes(raw)
        row = dict(id=batch['id'], category='stocks', target_count=1, series_count=1,
                   file=dict(path='batch.json', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        manifest = json.dumps(dict(schema='kuina-unique-queue-v1', batches=[row])).encode()
        (source / 'manifest.json').write_bytes(manifest)
        queue = UniqueQueue(self.base / 'queue', self.hub)
        queue.install(source / 'manifest.json')
        self.generation = hashlib.sha256(manifest).hexdigest()
        self.catalogue = PrivateCatalogue(queue.root, self.hub, self.generation)
        self.batch_id = batch['id']

    def test_missing_unused_mutable_directories_are_not_recreated(self):
        for name in ('claims', 'assignments', 'locks'):
            (self.catalogue.root / name).rmdir()
        value = self.catalogue.catalogue(self.batch_id)
        self.assertEqual(value['generation'], self.generation)
        self.assertFalse(value['assignment_enabled'])
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'unknown')
        self.assertTrue(all(not (self.catalogue.root / n).exists() for n in ('claims', 'assignments', 'locks')))

    def test_fence_blocks_old_starts_and_preserves_private_scope(self):
        self.catalogue.fence_legacy_starts()
        self.assertTrue(self.catalogue.catalogue(self.batch_id)['assignment_enabled'])
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'clear')
        with self.assertRaises(FileExistsError):
            self.hub.claim('old-task', 'emily')
        self.assertEqual(self.catalogue.read_batch(self.batch_id)['targets'][0]['series_ids'], ['original-private-series'])
        public = self.catalogue.public_catalogue()
        self.assertNotIn('original-private-series', json.dumps(public))
        self.assertNotIn(str(self.base), json.dumps(public))
        self.assertNotIn('uid', json.dumps(public))

    def test_existing_worker_is_not_released_or_overwritten(self):
        owner = self.hub.claim('old-task', 'juan')
        self.catalogue.fence_legacy_starts()
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'working')
        self.assertFalse(self.catalogue.catalogue(self.batch_id)['assignment_enabled'])
        self.hub.report('old-task', 'juan', 'in_progress', 'Existing worker can still report')
        self.assertEqual(self.hub.work_claim_record(self.task)[1], owner)

    def test_old_unique_worker_or_reservation_blocks_github_assignment(self):
        queue = self.catalogue.queue
        queue.claim(self.batch_id, 'emily')
        self.catalogue.fence_legacy_starts()
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'working')
        self.assertFalse(self.catalogue.catalogue(self.batch_id)['assignment_enabled'])

    def test_old_unique_api_cannot_start_after_github_migration_freeze(self):
        self.catalogue.fence_legacy_starts()
        with self.assertRaises(FileExistsError):
            self.catalogue.queue.claim(self.batch_id, 'emily')
        marker = self.catalogue.root / 'locks/global/github-authority.json'
        self.assertTrue(marker.is_file())
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'clear')

    def test_old_unique_reservation_is_not_available_for_github(self):
        self.catalogue.queue.assign(self.batch_id, 'emily', 77, 'volunteer')
        self.catalogue.fence_legacy_starts()
        self.assertEqual(self.catalogue.guard(self.batch_id, 'assign', None)['state'], 'blocked')

    def test_unknown_lock_and_changed_definition_fail_closed(self):
        lock = self.hub.root / 'task-locks/old-task'
        lock.mkdir()
        with self.assertRaises(ValueError):
            self.catalogue.fence_legacy_starts()
        self.assertEqual(list(lock.iterdir()), [])
        batch_path = self.catalogue.root / 'package/batch.json'
        batch_path.chmod(0o600)  # Deliberately corrupt this owned temporary fixture.
        batch_path.write_text('{}')
        with self.assertRaises(ValueError):
            self.catalogue.read_batch(self.batch_id)

    def test_wrong_generation_and_private_public_fields_rejected(self):
        with self.assertRaises(ValueError):
            PrivateCatalogue(self.catalogue.root, self.hub, '0' * 64)
        self.catalogue.fence_legacy_starts()
        public = self.catalogue.public_catalogue()
        row = public['batches'][0]
        self.assertEqual(set(row), {'id', 'category', 'target_count', 'series_count', 'definition_sha256', 'assignment_enabled'})

    def test_generation_changed_after_construction_rejects_export(self):
        path = self.catalogue.root / 'package/manifest.json'
        path.chmod(0o600)
        path.write_text('{}')
        with self.assertRaises(ValueError):
            self.catalogue.public_catalogue()


if __name__ == '__main__':
    unittest.main()

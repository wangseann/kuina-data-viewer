"""Read-only migration from real temporary Hub state; no external services."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coordination.task_manager import digest, write
from tests import test_github_private as private_fixtures
from tests.test_unique_dashboard import fixtures
from coordination.github_assignments_v2 import Assignments
from tests.test_github_assignments import AtomicGitHub, guard
try:
    from coordination.github_migration import export, encode
except ImportError:
    export = encode = None


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = private_fixtures.PrivateCatalogueTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.cat = self.fixture.catalogue
        self.hub = self.cat.legacy
        self.task = self.fixture.task
        summary, _ = fixtures()
        write(self.cat.root / 'publication.json', dict(schema='kuina-unique-publication-v1',
              manifest_sha256=self.cat.generation, summary=summary))

    def fence(self):
        self.cat.fence_legacy_starts()

    def tree(self):
        # Content/modes/names unchanged, including private journals.
        roots = [self.hub.root, self.cat.root]
        return {str(p): (p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
                for root in roots for p in [root, *root.rglob('*')]}

    def test_worker_report_private_source_preserved_no_export_writes(self):
        self.assertIsNotNone(export)
        owner = self.hub.claim(self.task['id'], 'seann')
        self.hub.report(self.task['id'], 'seann', 'blocked', 'PRIVATE-NOTE-NEVER-PUBLIC')
        self.fence()
        before = self.tree()
        result = export(self.cat)
        self.assertEqual(self.tree(), before)
        row = result['migration']['records'][0]
        self.assertEqual((row['person'], row['status'], row['created_at']), ('seann', 'blocked', owner['claimed_at']))
        self.assertEqual(row['definition_sha256'], digest(self.task))
        self.assertEqual(len(row['work_proof_sha256']), 64)
        public = json.dumps(result)
        for private in ('PRIVATE-NOTE-NEVER-PUBLIC', 'original-private-series', str(self.hub.root), '"uid"', '"scope"'):
            self.assertNotIn(private, public)
        self.assertFalse(result['catalogue']['batches'][0]['assignment_enabled'])
        self.assertEqual(result['provenance']['actual_workers'], 1)
        self.assertEqual(result['provenance']['sentinels_ignored'], 1)

    def test_all_six_current_reservations_including_unreferenced_bound_receipts(self):
        for i, person in enumerate(['seann', 'seann', 'emily', 'th', 'jion', 'vitoria'], 4):
            task = copy.deepcopy(self.task)
            task['id'] = 'legacy-reserved-' + str(i)
            write(self.hub.root / 'tasks' / (task['id'] + '.json'), task)
            self.hub.assign(task['id'], person, i, 'author' + str(i))
        self.fence()
        for i in range(4, 10):
            self.cat.queue.fence(self.hub.task('legacy-reserved-' + str(i)), self.cat.config)
        (self.hub.root / 'assignments/.keep').touch()
        result = export(self.cat)
        self.assertEqual(len(result['migration']['records']), 6)
        self.assertEqual({r['request_issue'] for r in result['migration']['receipts']}, set(range(4, 10)))
        self.assertEqual(len(result['catalogue']['legacy_definitions']), 6)
        defs = {r['batch_id']: r['definition_sha256'] for r in result['catalogue']['legacy_definitions']}
        def catalogue(batch):
            return dict(schema='kuina-assignment-catalogue-v1', batch_id=batch, generation=self.cat.generation,
                        definition_sha256=defs[batch], assignment_enabled=False)
        store = Assignments(AtomicGitHub(), catalogue, guard)
        store.initialize(result['migration'])
        self.assertEqual(len(store.snapshot()['ledger']['assignments']), 6)
        for row in result['migration']['records']:
            self.assertEqual(row['origin'], 'migration')
            self.assertEqual(row['status'], 'assigned')
            self.assertIsNotNone(row['author'])
            self.assertEqual(store.release(row['batch_id'], row['person'], row['author'], 99 + row['assignment_issue'],
                                           row['assignment_issue'])['status'], 'rejected')

    def reserve(self):
        self.hub.assign(self.task['id'], 'seann', 4, 'alice')
        self.fence()
        return self.hub.root / 'assignments' / (self.task['id'] + '.json')

    def test_history_release_unknown_receipt_or_missing_binding_hold(self):
        path = self.reserve()
        original = json.loads(path.read_text())
        changes = [dict(history=[original['current']]), dict(requests={}),
                   dict(requests={'5': dict(task_id=self.task['id'], request_issue=5,
                                            action='assign', person='seann', status='confirmed')}),
                   dict(current=None)]
        for delta in changes:
            write(path, dict(original, **delta))
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                export(self.cat)
        write(path, original)
        self.assertEqual(export(self.cat)['provenance']['reservations'], 1)

    def test_missing_fence_unknown_lock_or_unknown_worker_hold(self):
        with self.assertRaises(ValueError):
            export(self.cat)
        self.fence()
        (self.hub.root / 'task-locks/unknown').mkdir()
        with self.assertRaises(ValueError):
            export(self.cat)
        (self.hub.root / 'task-locks/unknown').rmdir()
        (self.hub.root / 'work-claims/unknown').mkdir()
        with self.assertRaises(ValueError):
            export(self.cat)

    def test_old_unique_worker_or_reservation_never_omitted(self):
        self.cat.queue.assign(self.fixture.batch_id, 'emily', 77, 'volunteer')
        self.fence()
        with self.assertRaises(ValueError):
            export(self.cat)

    def test_missing_old_unique_parents_remain_missing(self):
        self.fence()
        marker = self.cat.root / 'locks/global/github-authority.json'
        marker.unlink(); marker.parent.rmdir()
        for name in ('claims', 'assignments', 'locks'):
            (self.cat.root / name).rmdir()
        self.assertEqual(export(self.cat)['provenance']['actual_workers'], 0)
        self.assertTrue(all(not (self.cat.root / n).exists() for n in ('claims', 'assignments', 'locks')))

    def test_midscan_new_report_or_changed_publication_hold(self):
        self.hub.claim(self.task['id'], 'seann')
        self.fence()
        original = self.cat.public_catalogue
        def drift():
            value = original()
            self.hub.report(self.task['id'], 'seann', 'blocked', 'midscan')
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=drift), self.assertRaises(ValueError):
            export(self.cat)

    def test_cached_valid_self_service_cannot_hide_corrupt_current_mode(self):
        self.fence()
        self.assertTrue(self.hub.self_service())
        path = self.hub.root / 'self-service.json'
        original = json.loads(path.read_text())
        for change in [dict(schema_version=999), dict(status='disabled'), dict(enabled_at='invalid'),
                       dict(sentinel_ids=[]), dict(sentinel_ids=original['sentinel_ids'] * 2)]:
            write(path, dict(original, **change))
            with self.subTest(change=change), self.assertRaises(ValueError):
                export(self.cat)
        write(path, original)
        self.assertEqual(export(self.cat)['provenance']['sentinels_ignored'], 1)

    def test_mode_changes_during_export_hold(self):
        self.fence()
        path = self.hub.root / 'self-service.json'
        original = self.cat.public_catalogue
        def drift():
            value = original()
            current = json.loads(path.read_text())
            current['sentinel_ids'] = []
            write(path, current)
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=drift), self.assertRaises(ValueError):
            export(self.cat)

    def test_unreferenced_reservation_still_requires_exact_fence(self):
        task = copy.deepcopy(self.task)
        task['id'] = 'outside-current-manifest'
        write(self.hub.root / 'tasks' / (task['id'] + '.json'), task)
        self.hub.assign(task['id'], 'emily', 17, 'other-author')
        self.fence()
        with self.assertRaises(ValueError):
            export(self.cat)
        self.cat.queue.fence(task, self.cat.config)
        self.assertEqual(export(self.cat)['provenance']['reservations'], 1)

    def test_new_unknown_lock_or_reservation_mutation_midscan_hold(self):
        path = self.reserve()
        original = self.cat.public_catalogue
        def change_reservation():
            value = original()
            changed = json.loads(path.read_text())
            changed['current']['github_author'] = 'other-author'
            write(path, changed)
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=change_reservation), self.assertRaises(ValueError):
            export(self.cat)
        def new_lock():
            value = original()
            (self.hub.root / 'task-locks/late-unknown-lock').mkdir()
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=new_lock), self.assertRaises(ValueError):
            export(self.cat)

    def test_actual_batched_parent_is_not_a_worker_and_sentinels_ignored(self):
        from tests import test_task_batches as batch_fixtures
        from coordination.github_private import PrivateCatalogue
        from coordination.task_manager import Hub
        from coordination.unique_queue import UniqueQueue
        fixture = batch_fixtures.BatchTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.hub = Hub(fixture.hub.root.resolve())
        fixture.manifest = fixture.manifest.resolve()
        fixture.split()
        hub = fixture.hub
        hub.enable_self_service()
        task = fixture.children()[0]
        hub.assign(task['id'], 'seann', 42, 'Alice')
        source = fixture.root.resolve() / 'queue-source'
        source.mkdir()
        body = dict(schema='kuina-unique-batch-v1', id='unique-parent-check', targets=[dict(
            target_id='subject', legacy_tasks=[dict(id=task['id'], task_sha256=digest(task))],
            series_ids=['private-series'])])
        raw = json.dumps(body).encode()
        (source / 'batch.json').write_bytes(raw)
        rows = [dict(id=body['id'], category='stocks', target_count=1, series_count=1,
                     file=dict(path='batch.json', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))]
        manifest = json.dumps(dict(schema='kuina-unique-queue-v1', batches=rows)).encode()
        (source / 'manifest.json').write_bytes(manifest)
        queue = UniqueQueue(fixture.root.resolve() / 'unique-queue', hub)
        queue.install(source / 'manifest.json')
        cat = PrivateCatalogue(queue.root, hub, hashlib.sha256(manifest).hexdigest())
        summary, _ = fixtures()
        write(cat.root / 'publication.json', dict(schema='kuina-unique-publication-v1',
              manifest_sha256=cat.generation, summary=summary))
        cat.fence_legacy_starts()
        result = export(cat)
        self.assertEqual(result['provenance']['actual_workers'], 0)
        self.assertEqual(result['provenance']['parents_ignored'], 1)
        self.assertEqual(result['provenance']['sentinels_ignored'], 3)
        self.assertEqual([r['batch_id'] for r in result['migration']['records']], [task['id']])

    def test_unknown_journal_or_public_fields_rejected(self):
        self.hub.claim(self.task['id'], 'seann')
        self.fence()
        path = self.hub.root / 'work-claims' / self.task['id'] / 'private-extra.json'
        write(path, dict(secret='not an approved journal'))
        with self.assertRaises(ValueError):
            export(self.cat)
        path.unlink()
        original = self.cat.public_catalogue
        def private_field():
            value = original()
            value['batches'][0]['private_path'] = '/private'
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=private_field), self.assertRaises(ValueError):
            export(self.cat)

    def test_publication_generation_private_keys_and_output_caps(self):
        self.fence()
        path = self.cat.root / 'publication.json'
        saved = json.loads(path.read_text())
        for bad in [dict(saved, manifest_sha256='0' * 64), dict(saved, uid=123),
                    dict(saved, summary=dict(saved['summary'], private_path='/private'))]:
            write(path, bad)
            with self.assertRaises(ValueError):
                export(self.cat)
        write(path, saved)
        result = export(self.cat)
        raw, compressed = encode(result)
        self.assertEqual(json.loads(raw), json.loads(gzip.decompress(compressed)))
        with self.assertRaises(ValueError):
            encode(result, max_bytes=1)
        with self.assertRaises(ValueError):
            encode(result, max_compressed_bytes=1)

    def test_exact_empty_markers_all_five_namespaces_are_preserved(self):
        self.fence()
        markers = []
        for namespace in ('claims', 'work-claims', 'assignments', 'verified', 'task-locks'):
            path = self.hub.root / namespace / '.keep'
            path.write_bytes(b'')
            path.chmod(0o644)
            markers.append(path)
        before = self.tree()
        result = export(self.cat)
        self.assertEqual(self.tree(), before)
        self.assertEqual(result['provenance']['referenced_legacy_tasks'], 1)
        self.assertNotIn('.keep', json.dumps(result))
        self.assertTrue(all(p.read_bytes() == b'' and p.stat().st_mode & 0o777 == 0o644 for p in markers))

    def test_nonzero_marker_rejected_before_open_all_five_namespaces(self):
        from coordination.github_migration import _Epoch
        self.fence()
        for namespace in ('claims', 'work-claims', 'assignments', 'verified', 'task-locks'):
            path = self.hub.root / namespace / '.keep'
            path.write_bytes(b'UNKNOWN-CONTENT-DO-NOT-OPEN')
            path.chmod(0o644)
            reads = []
            original = _Epoch.read
            def track(epoch, selected, *args, **kwargs):
                reads.append(Path(selected))
                return original(epoch, selected, *args, **kwargs)
            with self.subTest(namespace=namespace), patch.object(_Epoch, 'read', track), self.assertRaises(ValueError):
                export(self.cat)
            self.assertNotIn(path, reads)
            path.unlink()

    def test_marker_wrong_mode_directory_or_symlink_rejected(self):
        self.fence()
        path = self.hub.root / 'claims/.keep'
        for mode in (0o444, 0o666):
            path.write_bytes(b'')
            path.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                export(self.cat)
            path.unlink()
        path.mkdir()
        with self.assertRaises(ValueError):
            export(self.cat)
        path.rmdir()
        target = self.hub.root / 'marker-target'
        target.write_bytes(b'')
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            export(self.cat)

    def test_marker_epoch_change_fails_closed(self):
        self.fence()
        path = self.hub.root / 'task-locks/.keep'
        path.write_bytes(b'')
        path.chmod(0o644)
        original = self.cat.public_catalogue
        def touch_marker():
            value = original()
            path.touch()
            return value
        with patch.object(self.cat, 'public_catalogue', side_effect=touch_marker), self.assertRaises(ValueError):
            export(self.cat)


if __name__ == '__main__':
    unittest.main()

import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coordination.task_manager import Hub, PEOPLE, digest, read, write, validate_public_snapshot


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hub = Hub(self.root / 'hub')
        self.hub.init()
        at = '2026-11-11T00:00:00+00:00'
        self.parent = dict(id='triage-example', category='stocks', kind='triage', assignee='juan',
                           effort=1, affected_series=1000, issues=[], created_at=at, audit_utc=at, scope=None)
        write(self.hub.root / 'tasks' / 'triage-example.json', self.parent)
        self.records = [dict(id=str(i), decision='ELIGIBLE' if i % 10 == 0 else 'INELIGIBLE') for i in range(1201)]
        self.page = self.root / 'page.json.gz'
        self.page.write_bytes(gzip.compress(json.dumps(dict(schema='kuina-series-page-v1', datasetId='private-id', series=self.records)).encode()))
        self.ref = dict(path=self.page.name, bytes=self.page.stat().st_size,
                        sha256=hashlib.sha256(self.page.read_bytes()).hexdigest(), rows=len(self.records))
        self.manifest = self.root / 'manifest.json'
        write(self.manifest, dict(schema='kuina-inspection-v1',
                                  auditUtc=at, requirements=dict(maxNativeSeconds=900, minHistoryYears=2),
                                  windowStart='2024-10-01', windowEnd='2026-10-01', datasets=[dict(id='private-id', type='stocks',
                                         series=1201, eligible=121, pages=[self.ref])]))

    def split(self, mode='lead'):
        return self.hub.split(self.manifest, mode, 500)

    def children(self):
        return [t for t in self.hub.tasks() if 'batch_spec' in t]

    def test_partition_idempotence_lead_and_legacy_claim_block(self):
        result = self.split()
        self.assertEqual(result['created'], 3)
        children = self.children()
        self.assertEqual([t['affected_series'] for t in children], [500, 500, 201])
        self.assertEqual([(t['batch_spec']['start'], t['batch_spec']['stop']) for t in children], [(0, 500), (500, 1000), (1000, 1201)])
        self.assertTrue(all(t['assignee'] == t['lead'] == 'juan' for t in children))
        self.assertEqual(self.hub.task(self.parent['id']), self.parent)
        self.assertEqual(self.hub.state(self.parent)[0], 'batched')
        self.assertEqual(self.split()['created'], 0)
        self.assertTrue((self.hub.root / 'claims' / self.parent['id']).exists())
        self.assertEqual(read(self.hub.root / 'claims' / self.parent['id'] / 'owner.json')['task_sha256'], digest(self.parent))
        self.assertEqual(list((self.hub.root / 'tasks').glob('batch-*')), [])
        with self.assertRaises(ValueError):
            self.hub.claim(self.parent['id'], 'juan')
        with self.assertRaises(ValueError):
            self.hub.split(self.manifest, 'balanced', 500)

    def test_claimed_parent_untouched_and_no_auto_recovery(self):
        self.hub.claim(self.parent['id'], 'juan')
        before = read(self.hub.root / 'claims' / self.parent['id'] / 'owner.json')
        self.assertEqual(self.split()['created'], 0)
        self.assertEqual(self.children(), [])
        self.assertEqual(read(self.hub.root / 'claims' / self.parent['id'] / 'owner.json'), before)
        plans = self.hub.root / 'batch-plans'
        (plans / '.triage-example.incoming').mkdir()
        with self.assertRaisesRegex(ValueError, 'reconcil'):
            self.hub.tasks()

    def test_balancing_counts_records_and_public_privacy(self):
        self.split('balanced')
        self.assertEqual([t['assignee'] for t in self.children()], list(PEOPLE)[:3])
        snapshot = self.hub.snapshot()
        self.assertEqual(snapshot['schema_version'], 2)
        self.assertEqual(snapshot['batch_limit'], 500)
        self.assertEqual(sum(p['remaining_series'] for p in snapshot['people']), 1201)
        self.assertEqual(sum(p['batched'] for p in snapshot['people']), 1)
        self.assertEqual(sum(p['load'] for p in snapshot['people']), 13)
        for private in ('batch_spec', 'private-id', str(self.manifest), 'sha256', 'decision'):
            self.assertNotIn(private, json.dumps(snapshot))
        for mutation in ('total', 'parent', 'owner', 'number'):
            broken = copy.deepcopy(snapshot)
            if mutation == 'total': broken['people'][0]['remaining_series'] += 1
            if mutation == 'parent': broken['tasks'][-1]['parent_id'] = 'absent'
            if mutation == 'owner': broken['tasks'][-1]['lead'] = 'emily'
            if mutation == 'number': broken['tasks'][-1]['batch_number'] = 99
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_public_snapshot(broken)

    def test_reader_hashes_and_eligible_skip(self):
        self.split()
        child = self.children()[0]
        result = self.hub.read_batch(child['id'])
        self.assertEqual(result['selected'], 500)
        self.assertEqual(result['skipped_eligible'], 50)
        self.assertEqual(len(result['records']), 450)
        self.assertTrue(all(r['decision'] == 'INELIGIBLE' for r in result['records']))
        self.page.write_bytes(self.page.read_bytes() + b'changed')
        with self.assertRaises(ValueError): self.hub.read_batch(child['id'])
        self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaises(ValueError): self.hub.read_batch(child['id'])

    def test_legacy_worker_winning_reservation_race_preserved(self):
        original_mkdir = Path.mkdir
        claim_path = self.hub.root / 'claims' / self.parent['id']
        owner = dict(person='juan', uid=os.getuid(), task_sha256=digest(self.parent),
                     claimed_at='2026-11-11T00:00:00+00:00')

        def racing_mkdir(path, *args, **kwargs):
            if path == claim_path and not path.exists():
                original_mkdir(path, mode=0o755)
                write(path / 'owner.json', owner)
                raise FileExistsError('legacy worker won')
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, 'mkdir', racing_mkdir):
            result = self.split('balanced')
        self.assertEqual(result, dict(created=0, activated=[], deferred=[self.parent['id']]))
        self.assertEqual(read(claim_path / 'owner.json'), owner)
        self.assertEqual(self.hub.state(self.parent)[0], 'active')
        self.assertEqual(self.children(), [])

    def test_interrupted_activation_reserves_parent_and_hides_children(self):
        with patch('coordination.task_manager.os.rename', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): self.split()
        self.assertTrue((self.hub.root / 'claims' / self.parent['id'] / 'owner.json').exists())
        self.assertEqual(list((self.hub.root / 'tasks').glob('batch-*')), [])
        for action in (self.hub.tasks, self.hub.snapshot, self.split,
                       lambda: self.hub.claim(self.parent['id'], 'juan')):
            with self.assertRaisesRegex(ValueError, 'reconcil'): action()

    def test_balancing_includes_remaining_unsplit_records(self):
        inventory = dict(self.parent, id='triage-held', category='emotions', assignee='juan', affected_series=2000)
        write(self.hub.root / 'tasks' / 'triage-held.json', inventory)
        self.split('balanced')
        self.assertEqual([t['assignee'] for t in self.children()], ['emily', 'brian', 'amir'])
        self.assertEqual(self.hub.review_loads()['juan'], 2000)
        self.assertEqual(len(self.hub.listing(limit=2)), 2)
        self.assertEqual(len(self.hub.listing(limit=2, offset=2)), 2)
        self.assertEqual(len(self.hub.listing(all_tasks=True)), 5)

    def test_manifest_tampering_and_wholly_eligible_dataset(self):
        manifest = read(self.manifest)
        manifest['datasets'][0]['eligible'] = 1201
        write(self.manifest, manifest)
        self.assertEqual(self.split()['created'], 0)
        self.assertEqual(self.hub.snapshot()['schema_version'], 1)
        manifest['datasets'][0]['eligible'] = 121
        write(self.manifest, manifest)
        self.split()
        child = self.children()[0]
        self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'manifest hash'): self.hub.read_batch(child['id'])
        with self.assertRaisesRegex(ValueError, 'differs'): self.split()

    def test_reader_rejects_unknown_decisions_and_bounded_decode(self):
        self.records[0]['decision'] = 'UNKNOWN'
        payload = dict(schema='kuina-series-page-v1', datasetId='private-id', series=self.records)
        self.page.write_bytes(gzip.compress(json.dumps(payload).encode()))
        self.ref.update(bytes=self.page.stat().st_size, sha256=hashlib.sha256(self.page.read_bytes()).hexdigest())
        manifest = read(self.manifest)
        manifest['datasets'][0]['pages'] = [self.ref]
        write(self.manifest, manifest)
        self.split()
        child = self.children()[0]
        with self.assertRaisesRegex(ValueError, 'decision'): self.hub.read_batch(child['id'])
        with patch('coordination.task_manager.gzip.GzipFile') as opener:
            opener.return_value.__enter__.return_value.read.return_value = b' ' * (32 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, '32 MiB'): self.hub.read_batch(child['id'])
            opener.return_value.__enter__.return_value.read.assert_called_once_with(32 * 1024 * 1024 + 1)

    def test_preflight_rejects_profile_windows_and_unusable_page_references(self):
        original = read(self.manifest)
        (self.root / 'linked').symlink_to(self.root, target_is_directory=True)
        (self.root / 'linked-page.gz').symlink_to(self.page)
        (self.root / 'directory').mkdir()
        cases = [
            ('requirements', dict(maxNativeSeconds=86400, minHistoryYears=1)),
            ('requirements', dict(maxNativeSeconds=900.0, minHistoryYears=2)),
            ('windowStart', '2025-10-01'),
            ('windowEnd', '2023-10-01'),
            ('windowStart', '20241001'),
            ('auditUtc', '2026-11-10T00:00:00+00:00'),
            ('path', 'missing.json.gz'),
            ('path', '../outside.json.gz'),
            ('path', str(self.page)),
            ('path', 'linked/page.json.gz'),
            ('path', 'linked-page.gz'),
            ('path', 'directory'),
            ('path', 'nested\\page.json.gz'),
            ('path', '.'),
            ('bytes', self.ref['bytes'] + 1),
            ('bytes', 32 * 1024 * 1024 + 1),
        ]
        for field, value in cases:
            manifest = copy.deepcopy(original)
            if field in ('path', 'bytes'):
                manifest['datasets'][0]['pages'][0][field] = value
            else:
                manifest[field] = value
            write(self.manifest, manifest)
            with self.subTest(field=field, value=value):
                with self.assertRaises((ValueError, OSError)):
                    self.split()
                self.assertEqual(self.hub.state(self.parent)[0], 'queued')
                self.assertFalse((self.hub.root / 'claims' / self.parent['id']).exists())
                self.assertEqual(self.children(), [])
                self.assertFalse((self.hub.root / 'batch-plans').exists())
        write(self.manifest, original)

    def test_invalid_limits_and_missing_category_remains_inventory(self):
        for limit in (0, 501, True):
            with self.assertRaises(ValueError): self.hub.split(self.manifest, 'lead', limit)
        other = dict(self.parent, id='triage-other', category='emotions', affected_series=0)
        write(self.hub.root / 'tasks' / 'triage-other.json', other)
        self.split()
        self.assertEqual(self.hub.state(other)[0], 'queued')
        self.assertEqual(next(t for t in self.hub.snapshot()['tasks'] if t['id'] == other['id'])['batch_total'], 0)


if __name__ == '__main__':
    unittest.main()

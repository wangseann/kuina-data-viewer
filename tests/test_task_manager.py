import copy
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import unittest

from coordination.task_manager import Hub, IDENTITY, PEOPLE, digest, overlaps, read, write, validate_public_snapshot


def claim_worker(root, task_id, person, queue):
    try:
        Hub(root).claim(task_id, person)
        queue.put(True)
    except (ValueError, OSError):
        queue.put(False)


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.hub = Hub(Path(self.temporary.name) / 'private-hub')
        self.hub.init()
        self.summary = read(Path(__file__).resolve().parents[1] / 'docs' / 'summary.json')

    def seed(self):
        self.hub.seed(self.summary)
        return self.hub.tasks()[0]

    def scope(self, **changes):
        scope = dict(provider='private-provider', instrument='private-instrument', venue='venue',
                     feed='feed', currency='GBp', adjustment='raw', start='2024-10-01', end='2026-10-01',
                     native_interval_seconds=900, native_resolution='native 15 minute', history='two calendar years',
                     coverage='session calendar', meaning='observed price', budgets='reviewed bounded policy')
        scope.update(changes)
        return scope

    def proposal(self, **changes):
        proposal = dict(category='stocks', kind='metadata', effort=2, affected_series=4,
                        issues=['calendar_unverified'], scope=self.scope())
        proposal.update(changes)
        return proposal

    def admitted(self, proposal=None):
        proposal_id = self.hub.propose(proposal or self.proposal(), 'juan')
        result = self.hub.admit(proposal_id)
        self.assertTrue(result['admitted'])
        return self.hub.task(result['task_id'])

    def completion(self, task):
        self.hub.claim(task['id'], task['assignee'])
        self.hub.report(task['id'], task['assignee'], 'completed', 'PRIVATE NOTE /secret/target')

    def receipt(self, task):
        at = datetime.now(timezone.utc).isoformat()
        return dict(kind='plan', task_sha256=digest(task), verified=True,
                    evidence='/private/audit-proof', verified_at=at)

    def test_seed_fair_idempotent_and_source_assessment_preserved(self):
        ids = self.hub.seed(self.summary)
        self.assertEqual(len(ids), len(self.summary['types']))
        self.assertEqual(self.hub.seed(self.summary), [])
        loads = self.hub.loads()
        self.assertEqual(set(loads), set(PEOPLE))
        self.assertLessEqual(max(loads.values()) - min(loads.values()), 1)
        for task in self.hub.tasks():
            self.assertEqual(task['assessment_utc'], self.summary['assessment_utc'])
            self.assertIn('issue_totals', task)

    def test_multiprocess_claim_is_exclusive(self):
        task = self.seed()
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        workers = [context.Process(target=claim_worker, args=(str(self.hub.root), task['id'], task['assignee'], queue))
                   for _ in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(20)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sum(queue.get(timeout=2) for _ in workers), 1)

    def test_restrictive_umask_preserves_shared_traversal_and_record_reads(self):
        previous_umask = os.umask(0o077)
        try:
            hub = Hub(Path(self.temporary.name) / 'restrictive-hub')
            hub.init()
            self.assertEqual(stat.S_IMODE(hub.root.stat().st_mode), 0o755)
            task_id = hub.seed(self.summary)[0]
            task = hub.task(task_id)
            hub.claim(task_id, task['assignee'])
            claim = hub.root / 'claims' / task_id
            self.assertEqual(stat.S_IMODE(claim.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((claim / 'owner.json').stat().st_mode), 0o644)
            proposal_id = hub.propose(self.proposal(), 'juan')
            proposal = hub.root / 'proposals' / proposal_id
            self.assertEqual(stat.S_IMODE(proposal.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((proposal / 'proposal.json').stat().st_mode), 0o644)
            os.chmod(hub.root, 0o750)
            hub.init()
            self.assertEqual(stat.S_IMODE(hub.root.stat().st_mode), 0o750)
        finally:
            os.umask(previous_umask)

    def test_newer_audit_waits_for_unfinished_category_triage(self):
        task = self.seed()
        self.hub.claim(task['id'], task['assignee'])
        newer = copy.deepcopy(self.summary)
        newer['audit_utc'] = '2026-11-11T12:00:00+00:00'
        newer['assessment_utc'] = '2026-11-11T13:00:00+00:00'
        self.assertEqual(self.hub.seed(newer), [])
        self.assertEqual(self.hub.task(task['id']), task)
        self.hub.report(task['id'], task['assignee'], 'completed', 'Reviewed plan')
        self.assertEqual(self.hub.seed(newer), [])
        self.hub.verify(task['id'], self.receipt(task))
        older = copy.deepcopy(self.summary)
        older['audit_utc'] = '2026-11-08T12:00:00+00:00'
        self.assertEqual(self.hub.seed(older), [])
        created = self.hub.seed(newer)
        self.assertEqual(len(created), 1)
        follow_up = self.hub.task(created[0])
        self.assertEqual(follow_up['category'], task['category'])
        self.assertEqual(follow_up['audit_utc'], newer['audit_utc'])
        self.assertNotEqual(follow_up['id'], task['id'])
        self.assertEqual(self.hub.seed(newer), [])

    def test_claim_never_expires(self):
        task = self.seed()
        self.hub.claim(task['id'], task['assignee'])
        path = self.hub.root / 'claims' / task['id'] / 'owner.json'
        owner = read(path)
        owner['claimed_at'] = '1990-01-01T00:00:00+00:00'
        write(path, owner)
        with self.assertRaises(ValueError):
            self.hub.claim(task['id'], task['assignee'])

    def test_report_checks_person_uid_and_content_hash(self):
        task = self.seed()
        self.hub.claim(task['id'], task['assignee'])
        wrong = next(p for p in PEOPLE if p != task['assignee'])
        with self.assertRaises(ValueError):
            self.hub.report(task['id'], wrong, 'completed', 'test')
        path = self.hub.root / 'claims' / task['id'] / 'owner.json'
        owner = read(path)
        owner['uid'] = os.getuid() + 1
        write(path, owner)
        with self.assertRaises(ValueError):
            self.hub.report(task['id'], task['assignee'], 'completed', 'test')
        owner['uid'] = os.getuid()
        write(path, owner)
        task['effort'] += 1
        write(self.hub.root / 'tasks' / (task['id'] + '.json'), task)
        with self.assertRaises(ValueError):
            self.hub.report(task['id'], task['assignee'], 'completed', 'test')

    def test_overlapping_resource_dedup_ignores_warning_category(self):
        first = self.admitted()
        proposal = self.proposal(category='other-markets', issues=['short_history'])
        proposal_id = self.hub.propose(proposal, 'emily')
        self.assertEqual(self.hub.admit(proposal_id)['conflicts_with'], first['id'])
        self.assertFalse(overlaps(self.scope(), self.scope(start='2026-10-01', end='2028-10-01')))
        self.assertFalse(overlaps(self.scope(), self.scope(currency='GBP')))
        self.assertTrue(overlaps(self.scope(), self.scope(instrument=None)))

    def test_unknown_scope_is_conservative_and_extra_fields_rejected(self):
        self.admitted(self.proposal(scope=self.scope(instrument=None)))
        proposal_id = self.hub.propose(self.proposal(), 'emily')
        self.assertFalse(self.hub.admit(proposal_id)['admitted'])
        with self.assertRaises(ValueError):
            self.hub.propose(self.proposal(command='rm something'), 'juan')
        with self.assertRaises(ValueError):
            self.hub.propose(self.proposal(issues=['private-title']), 'juan')

    def collection(self):
        scope = self.scope()
        preflight = dict(kind='preflight', verified=True, scope_sha256=digest(scope),
                         evidence='/private/preflight', verified_at=datetime.now(timezone.utc).isoformat(),
                         checks={k: True for k in ('native_resolution', 'history', 'coverage', 'meaning', 'budgets')})
        return self.proposal(kind='collection', scope=scope, preflight=preflight)

    def test_collection_admission_requires_exact_preflight(self):
        with self.assertRaises(ValueError):
            self.hub.propose(self.proposal(kind='collection'), 'juan')
        proposal = self.collection()
        proposal['scope']['meaning'] = 'changed after preflight'
        with self.assertRaises(ValueError):
            self.hub.propose(proposal, 'juan')
        proposal = self.collection()
        proposal['preflight']['checks']['budgets'] = False
        with self.assertRaises(ValueError):
            self.hub.propose(proposal, 'juan')

    def test_completion_does_not_verify_data(self):
        task = self.seed()
        self.completion(task)
        self.assertEqual(self.hub.state(task)[0], 'awaiting_verification')
        receipt = self.receipt(task)
        receipt['verified_at'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):
            self.hub.verify(task['id'], receipt)
        self.assertFalse(self.hub.verify(task['id'], self.receipt(task))['certifies_data'])

    def test_collection_needs_fresh_exact_eligible_audit(self):
        task = self.admitted(self.collection())
        self.completion(task)
        scope = task['scope']
        receipt = self.receipt(task)
        receipt.update(kind='audit', scope_sha256=digest(scope), source_identity={k: scope[k] for k in IDENTITY},
                       window={k: scope[k] for k in ('start', 'end')}, native_interval_seconds=900,
                       unexplained_gaps=0, eligible=True, audited_at=receipt['verified_at'])
        for field, bad in [('audited_at', '2000-01-01T00:00:00+00:00'), ('unexplained_gaps', 1),
                           ('eligible', False), ('native_interval_seconds', 3600),
                           ('window', {'start': '2025-01-01', 'end': '2026-01-01'}),
                           ('source_identity', {}), ('scope_sha256', 'wrong')]:
            broken = copy.deepcopy(receipt)
            broken[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.hub.verify(task['id'], broken)
        self.assertTrue(self.hub.verify(task['id'], receipt)['certifies_data'])

    def test_snapshot_is_strict_public_whitelist(self):
        task = self.admitted()
        self.completion(task)
        snapshot = self.hub.snapshot()
        encoded = json.dumps(snapshot)
        for forbidden in ('private-provider', 'private-instrument', 'PRIVATE NOTE', '/secret/', 'scope', 'preflight', 'issue_totals'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(set(snapshot), {'schema_version', 'updated_at', 'profile', 'people', 'tasks'})
        self.assertEqual(set(snapshot['tasks'][0]), {'id', 'category', 'kind', 'status', 'assignee', 'effort',
                                                  'affected_series', 'issues', 'created_at', 'updated_at'})

    def test_verified_plan_allows_scoped_successor_but_never_parallel_work(self):
        metadata = self.admitted()
        preflight = self.proposal(kind='preflight')
        proposal_id = self.hub.propose(preflight, 'emily')
        self.assertFalse(self.hub.admit(proposal_id)['admitted'])
        self.completion(metadata)
        self.hub.verify(metadata['id'], self.receipt(metadata))
        result = self.hub.admit(proposal_id)
        self.assertTrue(result['admitted'])
        task = self.hub.task(result['task_id'])
        collection_id = self.hub.propose(self.collection(), 'juan')
        self.assertFalse(self.hub.admit(collection_id)['admitted'])
        self.completion(task)
        self.hub.verify(task['id'], self.receipt(task))
        self.assertTrue(self.hub.admit(collection_id)['admitted'])

    def test_worker_cannot_inject_verified_status_or_public_timestamp_text(self):
        task = self.seed()
        self.hub.claim(task['id'], task['assignee'])
        record = self.hub.report(task['id'], task['assignee'], 'in_progress', 'test')
        injected = self.hub.root / 'claims' / task['id'] / 'report-injected.json'
        for field, value in [('status', 'verified'), ('at', 'PRIVATE PATH /secret/')]:
            broken = dict(record)
            broken[field] = value
            write(injected, broken)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.hub.snapshot()
        injected.unlink()
        self.assertEqual(self.hub.state(task)[0], 'active')

    def test_public_validator_rejects_extra_fields_and_inconsistent_totals(self):
        self.seed()
        snapshot = self.hub.snapshot()
        self.assertIs(validate_public_snapshot(snapshot), snapshot)
        for change in ('scope', 'total', 'reason'):
            broken = copy.deepcopy(snapshot)
            if change == 'scope':
                broken['tasks'][0]['scope'] = '/secret/'
            elif change == 'total':
                broken['people'][0]['load'] += 1
            else:
                broken['tasks'][0]['issues'] = ['private-reason']
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_public_snapshot(broken)


if __name__ == '__main__':
    unittest.main()

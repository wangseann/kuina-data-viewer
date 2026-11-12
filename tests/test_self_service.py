"""Self-service reservations never substitute for an actual Unix worker claim."""
import copy
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from coordination.task_manager import Hub, PEOPLE, digest, read, write, validate_public_snapshot


def racing_action(root, task_id, action, start, results):
    hub = Hub(root)
    start.wait(10)
    try:
        if action == 'assign':
            hub.assign(task_id, 'emily', 42, 'volunteer')
        else:
            hub.claim(task_id, 'juan')
        results.put((action, True))
    except (ValueError, OSError):
        results.put((action, False))


class SelfServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.hub = Hub(Path(self.temporary.name) / 'hub')
        self.hub.init()
        summary = read(Path(__file__).resolve().parents[1] / 'docs' / 'summary.json')
        self.hub.seed(summary)
        self.originals = self.hub.tasks()
        self.task = self.originals[0]

    def enable(self):
        return self.hub.enable_self_service()

    def reserve(self, person='emily', issue=42):
        return self.hub.assign(self.task['id'], person, issue, 'volunteer')

    def test_available_ignores_old_assignments_and_preserves_definitions(self):
        self.enable()
        self.assertEqual(self.hub.tasks(), self.originals)
        snapshot = self.hub.snapshot()
        self.assertEqual(snapshot['schema_version'], 3)
        self.assertTrue(all(t['status'] == 'available' and t['assignee'] is None for t in snapshot['tasks']))
        self.assertTrue(all('effort' not in t and 'lead' not in t for t in snapshot['tasks']))
        self.assertTrue(all(p['assigned'] == p['remaining_series'] == 0 for p in snapshot['people']))
        row = self.hub.listing(available=True, category=self.task['category'])[0]
        self.assertEqual(row['task_sha256'], digest(self.task))
        self.assertIsNone(row['assignee'])
        self.assertNotIn('effort', row)
        self.assertNotIn('lead', row)

    def test_legacy_claims_blocked_and_existing_claim_grandfathered(self):
        old = self.originals[1]
        self.hub.claim(old['id'], old['assignee'])
        self.enable()
        config = read(self.hub.root / 'self-service.json')
        self.assertNotIn(old['id'], config['sentinel_ids'])
        self.assertEqual(self.hub.state(old)[0], 'active')
        self.hub.report(old['id'], old['assignee'], 'in_progress', 'Existing work continues')
        # A literal old-style mkdir cannot bypass the policy, even when state was cached.
        with self.assertRaises(FileExistsError):
            (self.hub.root / 'claims' / self.task['id']).mkdir()
        _, sentinel = self.hub.claim_record(self.task)
        self.assertEqual(sentinel['task_sha256'], digest(self.task))
        self.assertEqual(sentinel['person'], self.task['assignee'])
        self.assertEqual(sentinel['uid'], os.getuid())
        with self.assertRaises(ValueError):
            self.hub.report(self.task['id'], self.task['assignee'], 'in_progress', 'Cannot report sentinel')

    def test_reservation_idempotence_conflict_release_history(self):
        self.enable()
        self.assertEqual(self.reserve(), dict(status='assigned', task_id=self.task['id'], person='emily', issue=42))
        self.assertEqual(self.reserve(issue=43)['issue'], 42)
        self.assertFalse((self.hub.root / 'work-claims' / self.task['id']).exists())
        with self.assertRaises(ValueError):
            self.reserve('juan')
        with self.assertRaises(ValueError):
            self.hub.claim(self.task['id'], 'juan')
        with self.assertRaises(ValueError):
            self.hub.release_assignment(self.task['id'], 'emily', 'other-author')
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer')
        self.assertEqual(self.hub.state(self.task)[0], 'available')
        record = read(self.hub.root / 'assignments' / (self.task['id'] + '.json'))
        self.assertEqual(len(record['history']), 1)
        self.assertEqual(record['history'][0]['issue'], 42)
        self.reserve('juan', 44)
        self.hub.claim(self.task['id'], 'juan')
        with self.assertRaises(ValueError):
            self.hub.release_assignment(self.task['id'], 'juan', 'volunteer', coordinator=True)

    def test_actual_claim_reports_and_public_schema(self):
        self.enable()
        self.reserve()
        owner = self.hub.claim(self.task['id'], 'emily')
        self.assertEqual(owner['uid'], os.getuid())
        self.assertEqual(owner['task_sha256'], digest(self.task))
        with self.assertRaises(ValueError):
            self.hub.report(self.task['id'], 'juan', 'completed', 'Wrong person')
        self.hub.report(self.task['id'], 'emily', 'blocked', 'PRIVATE PATH /private/work')
        snapshot = self.hub.snapshot()
        row = next(t for t in snapshot['tasks'] if t['id'] == self.task['id'])
        self.assertEqual(row['assignee'], 'emily')
        self.assertEqual(row['assignment_issue'], 42)
        self.assertEqual(row['status'], 'blocked')
        person = next(p for p in snapshot['people'] if p['id'] == 'emily')
        self.assertEqual(person['active'], 1)
        self.assertEqual(person['remaining_series'], self.task['affected_series'])
        self.assertNotIn('PRIVATE', str(snapshot))
        self.assertNotIn('volunteer', str(snapshot))
        for field, value in [('effort', 1), ('lead', 'juan'), ('scope', {})]:
            invalid = copy.deepcopy(snapshot)
            invalid['tasks'][0][field] = value
            with self.assertRaises(ValueError):
                validate_public_snapshot(invalid)
        invalid = copy.deepcopy(snapshot)
        next(t for t in invalid['tasks'] if t['id'] == self.task['id'])['assignee'] = None
        with self.assertRaises(ValueError):
            validate_public_snapshot(invalid)

    def test_assignment_and_worker_share_persistent_job_lock(self):
        self.enable()
        lock = self.hub.root / 'task-locks' / self.task['id']
        lock.mkdir()
        for action in (self.reserve, lambda: self.hub.claim(self.task['id'], 'emily')):
            with self.assertRaises(FileExistsError):
                action()
        self.assertTrue(lock.exists())
        self.assertFalse((self.hub.root / 'work-claims' / self.task['id']).exists())
        lock.rmdir()
        self.hub.claim(self.task['id'], 'emily')
        with self.assertRaises(ValueError):
            self.reserve('juan')

    def test_modes_and_actual_uid_are_enforced(self):
        self.enable()
        for name in ('work-claims', 'task-locks'):
            self.assertEqual(stat.S_IMODE((self.hub.root / name).stat().st_mode), 0o1777)
        for path in (self.hub.root / 'assignments', self.hub.root / 'self-service.json'):
            self.assertFalse(path.stat().st_mode & 0o022)
        self.hub.claim(self.task['id'], 'emily')
        claim = self.hub.root / 'work-claims' / self.task['id']
        self.assertEqual(stat.S_IMODE(claim.stat().st_mode), 0o755)
        owner = read(claim / 'owner.json')
        owner['uid'] += 1
        write(claim / 'owner.json', owner)
        with self.assertRaises(ValueError):
            self.hub.report(self.task['id'], 'emily', 'completed', 'Wrong Unix owner')

    def test_interrupted_migration_fails_closed_and_is_not_repeated(self):
        original_write = write
        def interrupt(path, value):
            if path.name == 'owner.json':
                raise OSError('simulated interruption')
            return original_write(path, value)
        with patch('coordination.task_manager.write', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.enable()
        self.assertTrue((self.hub.root / '.self-service-migration-lock').exists())
        with self.assertRaises(ValueError):
            Hub(self.hub.root).snapshot()
        with self.assertRaises((ValueError, FileExistsError)):
            Hub(self.hub.root).enable_self_service()

    def test_assignment_status_is_safe_and_hash_bound(self):
        self.enable()
        self.assertEqual(self.hub.assignment_status(self.task['id']),
                         dict(task_id=self.task['id'], status='available', assignee=None, assignment_issue=None))
        self.reserve()
        self.assertEqual(self.hub.assignment_status(self.task['id']),
                         dict(task_id=self.task['id'], status='assigned', assignee='emily', assignment_issue=42))
        changed = dict(self.task, affected_series=self.task['affected_series'] + 1)
        write(self.hub.root / 'tasks' / (self.task['id'] + '.json'), changed)
        with self.assertRaises(ValueError):
            self.hub.claim(self.task['id'], 'emily')

    def test_completed_assign_request_cannot_resurrect_released_reservation(self):
        self.enable()
        self.reserve()
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer')
        self.reserve()
        self.assertEqual(self.hub.state(self.task)[0], 'available')
        self.assertEqual(self.hub.request_status(self.task['id'], 42),
                         dict(task_id=self.task['id'], request_issue=42, action='assign',
                              person='emily', status='confirmed'))

    def test_completed_release_request_cannot_release_a_later_reservation(self):
        self.enable()
        self.reserve()
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer',
                                    request_issue=43, assignment_issue=42)
        self.reserve(issue=44)
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer',
                                    request_issue=43, assignment_issue=42)
        self.assertEqual(self.hub.assignment_status(self.task['id'])['assignment_issue'], 44)
        self.assertEqual(self.hub.request_status(self.task['id'], 43),
                         dict(task_id=self.task['id'], request_issue=43, action='release',
                              person='emily', status='released'))

    def test_release_request_is_bound_to_expected_reservation(self):
        self.enable()
        self.reserve()
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer')
        self.reserve(issue=44)
        with self.assertRaises(ValueError):
            self.hub.release_assignment(self.task['id'], 'emily', 'volunteer',
                                        request_issue=43, assignment_issue=42)
        self.assertEqual(self.hub.assignment_status(self.task['id'])['assignment_issue'], 44)

    def test_native_outcome_is_atomic_with_assignment_and_survives_lost_ack(self):
        self.enable()
        original_write = write
        path = self.hub.root / 'assignments' / (self.task['id'] + '.json')
        def lost_ack(target, value):
            original_write(target, value)
            if target == path:
                raise OSError('lost acknowledgement after atomic write')
        with patch('coordination.task_manager.write', side_effect=lost_ack):
            with self.assertRaises(OSError):
                self.reserve()
        restarted = Hub(self.hub.root)
        self.assertEqual(restarted.request_status(self.task['id'], 42)['status'], 'confirmed')
        restarted.release_assignment(self.task['id'], 'emily', 'volunteer')
        restarted.assign(self.task['id'], 'emily', 42, 'volunteer')
        self.assertEqual(restarted.state(self.task)[0], 'available')

    def test_release_outcome_survives_lost_ack_and_new_reservation(self):
        self.enable()
        self.reserve()
        original_write = write
        path = self.hub.root / 'assignments' / (self.task['id'] + '.json')
        def lost_ack(target, value):
            original_write(target, value)
            if target == path:
                raise OSError('lost acknowledgement after atomic release')
        with patch('coordination.task_manager.write', side_effect=lost_ack):
            with self.assertRaises(OSError):
                self.hub.release_assignment(self.task['id'], 'emily', 'volunteer',
                                            request_issue=43, assignment_issue=42)
        restarted = Hub(self.hub.root)
        self.assertEqual(restarted.request_status(self.task['id'], 43)['status'], 'released')
        restarted.assign(self.task['id'], 'emily', 44, 'volunteer')
        restarted.release_assignment(self.task['id'], 'emily', 'volunteer',
                                      request_issue=43, assignment_issue=42)
        self.assertEqual(restarted.assignment_status(self.task['id'])['assignment_issue'], 44)

    def test_legacy_assignment_history_prevents_reusing_released_issue(self):
        self.enable()
        self.reserve()
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer')
        path = self.hub.root / 'assignments' / (self.task['id'] + '.json')
        record = read(path)
        del record['requests']
        write(path, record)
        self.reserve()
        self.assertEqual(self.hub.state(self.task)[0], 'available')
        self.assertEqual(self.hub.request_status(self.task['id'], 42)['status'], 'confirmed')

    def test_second_request_for_existing_reservation_has_durable_receipt(self):
        self.enable()
        self.reserve()
        self.reserve(issue=43)
        self.hub.release_assignment(self.task['id'], 'emily', 'volunteer')
        self.reserve(issue=43)
        self.assertEqual(self.hub.state(self.task)[0], 'available')
        self.assertEqual(self.hub.request_status(self.task['id'], 43)['action'], 'assign')

    def test_request_receipts_reject_edited_action_or_participant(self):
        self.enable()
        self.reserve()
        with self.assertRaises(ValueError):
            self.reserve('juan')
        with self.assertRaises(ValueError):
            self.hub.release_assignment(self.task['id'], 'emily', 'volunteer',
                                        request_issue=42, assignment_issue=42)
        self.assertIsNone(self.hub.request_status(self.task['id'], 999))

    def test_migration_preserves_legacy_worker_winning_exact_mkdir_race(self):
        original_mkdir = Path.mkdir
        legacy = self.hub.root / 'claims' / self.task['id']
        worker = dict(uid=os.getuid(), person=self.task['assignee'],
                      task_sha256=digest(self.task), claimed_at=self.task['created_at'])
        def racing_mkdir(path, *args, **kwargs):
            if path == legacy and not path.exists():
                original_mkdir(path, mode=0o755)
                write(path / 'owner.json', worker)
                raise FileExistsError('legacy worker won')
            return original_mkdir(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', racing_mkdir):
            self.enable()
        self.assertNotIn(self.task['id'], read(self.hub.root / 'self-service.json')['sentinel_ids'])
        self.assertEqual(read(legacy / 'owner.json'), worker)
        self.assertEqual(self.hub.state(self.task)[0], 'active')

    def test_no_automatic_allocation_and_effort_optional_for_new_proposals(self):
        self.enable()
        for action in (self.hub.assign, self.hub.loads, self.hub.review_loads):
            with self.assertRaises(ValueError):
                action()
        scope = dict(provider='p', instrument='i', venue='v', feed='f', currency='c', adjustment='raw',
                     start='2024-10-01', end='2026-10-01', native_interval_seconds=900,
                     native_resolution='native', history='two years', coverage='calendar',
                     meaning='price', budgets='bounded')
        proposal = dict(category='stocks', kind='metadata', affected_series=3, issues=[], scope=scope)
        proposal_id = self.hub.propose(proposal, 'juan')
        result = self.hub.admit(proposal_id)
        task = self.hub.task(result['task_id'])
        self.assertIsNone(task['assignee'])
        self.assertNotIn('effort', task)
        self.assertEqual(self.hub.state(task)[0], 'available')
        self.hub.claim(task['id'], 'taha')
        self.assertEqual(self.hub.effective_assignee(task), 'taha')

    def test_restrictive_umask_and_simulated_noncoordinator_uid(self):
        previous = os.umask(0o077)
        try:
            self.enable()
            self.reserve()
            actual_uid = os.getuid()
            worker_uid = actual_uid + 1000
            original_stat = Path.stat
            worker_path = self.hub.root / 'work-claims' / self.task['id']
            lock_path = self.hub.root / 'task-locks' / self.task['id']
            def worker_stat(path, *args, **kwargs):
                value = original_stat(path, *args, **kwargs)
                if path == worker_path or worker_path in path.parents or path == lock_path:
                    fields = list(value)
                    fields[4] = worker_uid
                    return os.stat_result(fields)
                return value
            # Simulate a distinct filesystem UID without privileged setuid/chown.
            with patch('coordination.task_manager.os.getuid', return_value=worker_uid), patch.object(Path, 'stat', worker_stat):
                owner = self.hub.claim(self.task['id'], 'emily')
                self.assertEqual(owner['uid'], worker_uid)
                report = self.hub.report(self.task['id'], 'emily', 'completed', 'Distinct UID evidence')
                self.assertEqual(report['uid'], worker_uid)
                self.assertEqual(self.hub.state(self.task)[0], 'awaiting_verification')
                with self.assertRaises(ValueError):
                    self.reserve('juan')
            self.assertEqual(stat.S_IMODE(worker_path.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((worker_path / 'owner.json').stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE((self.hub.root / 'work-claims').stat().st_mode), 0o1777)
        finally:
            os.umask(previous)

    def test_schema3_preserves_batch_partitions_and_removes_parent_ownership(self):
        import test_task_batches as batches
        fixture = batches.BatchTests(methodName='test_partition_idempotence_lead_and_legacy_claim_block')
        fixture.setUp()
        self.addCleanup(fixture.tmp.cleanup)
        fixture.split('balanced')
        original = fixture.hub.tasks()
        fixture.hub.enable_self_service()
        self.assertEqual(original, fixture.hub.tasks())
        snapshot = fixture.hub.snapshot()
        parent = next(t for t in snapshot['tasks'] if t['id'] == fixture.parent['id'])
        self.assertEqual(parent['status'], 'batched')
        self.assertIsNone(parent['assignee'])
        self.assertIsNone(parent['assignment_issue'])
        self.assertEqual(sum(p['remaining_series'] for p in snapshot['people']), 0)
        children = fixture.children()
        fixture.hub.claim(children[0]['id'], 'jion')
        self.assertEqual(fixture.hub.listing(person='jion')[0]['assignee'], 'jion')
        self.assertEqual(fixture.hub.read_batch(children[0]['id'])['selected'], 500)
        # batch_plans must still validate original parents via legacy claim_record.
        self.assertIn(fixture.parent['id'], fixture.hub.batch_plans())

    def test_mode_configuration_is_read_once_per_hub_instance(self):
        self.enable()
        hub = Hub(self.hub.root)
        with patch('coordination.task_manager.read', wraps=read) as reading:
            hub.snapshot()
            config_reads = [c for c in reading.call_args_list if c.args[0].name == 'self-service.json']
        self.assertEqual(len(config_reads), 1)

    def test_concurrent_worker_and_reservation_cannot_disagree(self):
        self.enable()
        context = multiprocessing.get_context('spawn')
        start, results = context.Event(), context.Queue()
        processes = [context.Process(target=racing_action,
                                     args=(str(self.hub.root), self.task['id'], action, start, results))
                     for action in ('assign', 'claim')]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(20)
            self.assertEqual(process.exitcode, 0)
        outcomes = dict(results.get(timeout=2) for _ in processes)
        self.assertEqual(sum(outcomes.values()), 1)
        state = self.hub.assignment_status(self.task['id'])
        if outcomes['assign']:
            self.assertEqual((state['status'], state['assignee']), ('assigned', 'emily'))
        else:
            self.assertEqual((state['status'], state['assignee']), ('active', 'juan'))

    def test_coordinator_override_before_claim_and_owner_only_mutations(self):
        self.enable()
        self.reserve()
        actual_uid = os.getuid()
        with patch('coordination.task_manager.os.getuid', return_value=actual_uid + 1000):
            with self.assertRaises(ValueError):
                self.hub.release_assignment(self.task['id'], 'emily', 'other', coordinator=True)
            with self.assertRaises(ValueError):
                self.hub.assign(self.task['id'], 'emily', 42, 'volunteer')
        self.hub.release_assignment(self.task['id'], 'emily', 'other', coordinator=True)
        self.assertEqual(self.hub.assignment_status(self.task['id'])['status'], 'available')

    def test_invalid_shared_permissions_fail_closed(self):
        self.enable()
        os.chmod(self.hub.root / 'work-claims', 0o777)
        with self.assertRaises(ValueError):
            Hub(self.hub.root).claim(self.task['id'], 'emily')

    def test_schema3_rejects_impossible_totals_and_assignment_origins(self):
        self.enable()
        self.reserve()
        snapshot = self.hub.snapshot()
        for issue in (0, -1, True, 1.5, '42'):
            invalid = copy.deepcopy(snapshot)
            next(t for t in invalid['tasks'] if t['id'] == self.task['id'])['assignment_issue'] = issue
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                validate_public_snapshot(invalid)
        invalid = copy.deepcopy(snapshot)
        next(p for p in invalid['people'] if p['id'] == 'emily')['remaining_series'] += 1
        with self.assertRaises(ValueError):
            validate_public_snapshot(invalid)
        invalid = copy.deepcopy(snapshot)
        next(t for t in invalid['tasks'] if t['status'] == 'available')['assignment_issue'] = 42
        with self.assertRaises(ValueError):
            validate_public_snapshot(invalid)


if __name__ == '__main__':
    unittest.main()

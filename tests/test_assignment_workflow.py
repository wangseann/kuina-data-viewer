"""Whole request-to-private-report flow with an atomic GitHub test server."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from coordination.github_assignments_v2 import Assignments
from coordination.github_backend import AuthorityBackend
from coordination.github_claims import process_issue
import test_github_assignments as github_fixtures
import test_github_task_manager as private_fixtures


class PrivateRoute:
    def __init__(self, manager):
        self.manager = manager

    def command(self, command, *arguments):
        if command != 'authorize-github-work' or arguments[0] != '--authorization':
            raise AssertionError('Unexpected private operation')
        return self.manager.authorize(json.loads(arguments[1]))


class AssignmentWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixture = private_fixtures.ManagerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.manager, self.catalogue, self.batch = fixture.manager, fixture.catalogue, fixture.batch
        self.catalogue.fence_legacy_starts()
        self.github = github_fixtures.AtomicGitHub()
        self.notifications = []
        self.github.finish = lambda issue, result: self.notifications.append(result)
        self.store = Assignments(self.github, self.catalogue.catalogue, self.manager.guard)
        self.store.initialize(dict(schema='kuina-assignment-migration-v1', complete=True,
                                   source_sha256='a' * 64, catalogue_generation=fixture.fixture.generation,
                                   records=[], receipts=[]))
        self.backend = AuthorityBackend(self.store, PrivateRoute(self.manager))

    def claim_issue(self):
        payload = dict(version=1, action='assign', task_id=self.batch, person='seann')
        return dict(number=42, title='[Kuina claim] ' + self.batch,
                    body='<!-- kuina-request-v1\n' + json.dumps(payload) + '\n-->',
                    user=dict(login='alice'))

    def start(self):
        result = process_issue(self.claim_issue(), self.github, self.backend, 'owner')
        self.assertEqual(result['status'], 'confirmed')
        self.assertFalse((self.catalogue.legacy.root / 'work-claims' / self.batch).exists())
        preparation = self.manager.prepare_work(self.batch, 'seann', 42)
        query = parse_qs(urlsplit(preparation['github_start_url']).query)
        issue = dict(number=43, title=query['title'][0], body=query['body'][0], user=dict(login='alice'))
        self.assertEqual(process_issue(issue, self.github, self.backend, 'owner')['status'], 'started')
        return preparation

    def test_claim_prepare_github_start_private_claim_and_report(self):
        preparation = self.start()
        self.assertEqual(self.store.status(self.batch)['status'], 'active')
        self.manager.claim(preparation['proof_sha256'])
        self.assertEqual(self.manager.read_batch(self.batch)['targets'][0]['series_ids'], ['original-private-series'])
        self.manager.report(self.batch, 'seann', 'in_progress', 'Private repair investigation')
        self.manager.report(self.batch, 'seann', 'completed', 'Ready for independent scientific checks')
        self.assertEqual(self.manager.show(self.batch)['status'], 'awaiting_verification')
        self.assertEqual(self.store.status(self.batch)['status'], 'active')

    def test_private_start_failure_never_releases_the_permanent_working_record(self):
        preparation = self.start()
        self.manager.protocol().preparation_path(preparation['proof_sha256']).unlink()
        with self.assertRaises(FileNotFoundError):
            self.manager.claim(preparation['proof_sha256'])
        self.assertEqual(self.store.status(self.batch)['status'], 'active')
        result = self.store.release(self.batch, 'seann', 'alice', 44, 42)
        self.assertEqual(result['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()

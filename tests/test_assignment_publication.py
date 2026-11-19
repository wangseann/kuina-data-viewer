from copy import deepcopy
import unittest

from coordination.assignment_publication import task_snapshot, render_assets
import test_unique_dashboard as fixtures


class AssignmentPublicationTests(unittest.TestCase):
    def setUp(self):
        self.summary, tasks = fixtures.fixtures()
        row = tasks['batches'][0]
        self.catalogue = dict(schema='kuina-public-assignment-catalogue-v1', generation='b' * 64,
                              batches=[{k: row[k] for k in ('id', 'category', 'target_count', 'series_count')} | dict(
                                  definition_sha256='c' * 64, assignment_enabled=True)])
        self.ledger = dict(schema='kuina-github-assignments-v1',
                           migration=dict(complete=True, source_sha256='a' * 64, catalogue_generation='b' * 64),
                           assignments={}, receipts={})
        self.at = '2026-11-19T00:00:00Z'

    def test_one_observed_ledger_drives_every_batch_without_private_queries(self):
        self.ledger['assignments']['unique-stocks-001'] = dict(
            batch_id='unique-stocks-001', person='seann', author='wangseann', assignment_issue=4,
            status='assigned', definition_sha256='c' * 64, catalogue_generation='b' * 64,
            created_at=self.at, updated_at=self.at, origin='github', work_proof_sha256=None,
            working_request_issue=None)
        self.ledger['receipts']['4'] = dict(request_issue=4, batch_id='unique-stocks-001',
            action='assign', person='seann', author='wangseann', assignment_issue=None,
            proof_sha256=None, status='confirmed', recorded_at=self.at,
            definition_sha256='c' * 64, catalogue_generation='b' * 64, origin='github')
        before = deepcopy((self.summary, self.catalogue, self.ledger))
        result = task_snapshot(self.summary, self.catalogue, self.ledger, self.at)
        self.assertEqual(result['batches'][0]['assignee'], 'seann')
        self.assertEqual(result['batches'][0]['status'], 'assigned')
        self.assertEqual(before, (self.summary, self.catalogue, self.ledger))

    def test_existing_scope_blocker_and_definition_drift_never_become_available(self):
        self.catalogue['batches'][0]['assignment_enabled'] = False
        result = task_snapshot(self.summary, self.catalogue, self.ledger, self.at)
        self.assertEqual(result['batches'][0]['status'], 'blocked')
        self.assertEqual(result['batches'][0]['blocker_codes'], ['legacy_reservation'])
        self.ledger['migration']['catalogue_generation'] = '0' * 64
        with self.assertRaises(ValueError):
            task_snapshot(self.summary, self.catalogue, self.ledger, self.at)

    def test_publication_contains_only_three_closed_delegation_assets(self):
        assets = render_assets(self.summary, self.catalogue, self.ledger, self.at)
        self.assertEqual(set(assets), {'docs/unique.html', 'docs/unique-summary.json', 'docs/unique-tasks.json'})
        import json
        tasks = json.loads(assets['docs/unique-tasks.json'])
        self.assertEqual(tasks['batches'][0]['status'], 'available')
        self.assertIn(b'Claim via GitHub', assets['docs/unique.html'])
        self.assertNotIn(b'/datashare/', assets['docs/unique.html'])


if __name__ == '__main__':
    unittest.main()

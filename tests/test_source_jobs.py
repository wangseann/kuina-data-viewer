import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_github_private
from coordination.github_task_manager import Manager
from coordination.github_legacy import LegacyCatalogue
from coordination.github_work import encoded, sha
from coordination.source_jobs import confirm, catalogue_rows, public_definition
from coordination.task_manager import write


class SourceJobTests(unittest.TestCase):
    def setUp(self):
        fixture = test_github_private.PrivateCatalogueTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.hub = fixture.hub
        parent = self.hub.root / 'unique-work'
        parent.mkdir()
        queue = parent / 'original'
        fixture.catalogue.root.rename(queue)
        self.original = LegacyCatalogue(queue, self.hub, fixture.generation)
        self.original.fence_legacy_starts()
        write(self.hub.root / 'github-assignment-authority.json', dict(
            schema='kuina-private-github-authority-v1', queue_root=str(queue),
            generation=fixture.generation, repo='wangseann/kuina-data-viewer'))
        self.sources = json.loads((Path(__file__).resolve().parents[1] / 'docs/acquisition-sources.json').read_text())
        self.manifest = confirm(self.sources, ['crypto-spot-kraken'], fixture.generation)
        self.job = self.manifest['jobs'][0]
        folder = self.hub.root / 'source-jobs/releases/fixture'
        folder.mkdir(parents=True)
        self.manifest_path = folder / 'manifest.json'
        self.manifest_path.write_bytes(encoded(self.manifest))
        write(self.hub.root / 'source-jobs-current.json', dict(
            schema='kuina-source-job-authority-v1', base_generation=fixture.generation,
            manifest_path=str(self.manifest_path), manifest_sha256=sha(encoded(self.manifest))))
        self.manager = Manager(self.hub.root)

    def prepare(self):
        return self.manager.prepare_work(self.job['id'], 'seann', 42)

    def start(self):
        preparation = self.prepare()
        authorization = dict(schema='kuina-github-working-authorization-v1', batch_id=self.job['id'],
            person='seann', assignment_issue=42, proof_sha256=preparation['proof_sha256'],
            ledger_sha='a'*40, working_request_issue=43)
        self.manager.authorize(authorization)
        return self.manager.claim(preparation['proof_sha256'])

    def test_source_job_is_an_additive_catalogue_and_requires_real_native_claim(self):
        catalogue = self.manager.catalogue()
        self.assertIn(self.job['id'], catalogue.rows)
        self.assertEqual(catalogue.row(self.fixture.batch_id), self.original.row(self.fixture.batch_id))
        self.assertIn(self.job['id'], {r['id'] for r in catalogue.public_catalogue()['batches']})
        self.assertEqual(self.manager.read_batch(self.job['id']), self.job)
        preparation = self.prepare()
        with self.assertRaises(FileNotFoundError):
            self.manager.claim(preparation['proof_sha256'])
        self.assertFalse((self.hub.root / 'work-claims' / self.job['id']).exists())

    def test_owner_reports_completion_and_cannot_start_second_worker(self):
        owner = self.start()
        self.assertEqual(owner['uid'], os.getuid())
        self.manager.report(self.job['id'], 'seann', 'in_progress', 'PRIVATE evidence /private/path')
        with self.assertRaises(ValueError):
            self.manager.report(self.job['id'], 'juan', 'completed', 'Not my worker')
        self.manager.report(self.job['id'], 'seann', 'completed', 'Private output hashes')
        self.assertEqual(self.manager.show(self.job['id'])['status'], 'awaiting_verification')
        with self.assertRaises(ValueError):
            self.manager.report(self.job['id'], 'seann', 'in_progress', 'Cannot reopen')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_job_confirmation_rejects_paid_sources_and_overlapping_provider_jobs(self):
        bad = copy.deepcopy(self.sources)
        bad['sources'][0]['access'] = 'paid'
        with self.assertRaises(ValueError):
            confirm(bad, [bad['sources'][0]['id']], self.fixture.generation)
        with self.assertRaisesRegex(ValueError, 'One job per provider|[Dd]uplicate'):
            confirm(self.sources, ['crypto-spot-kraken'], self.fixture.generation, self.manifest)
        self.assertIn('preflight', self.job['instructions'])
        self.assertIn('shared overlap check', self.job['instructions'])
        self.assertEqual(catalogue_rows(self.manifest)[0]['definition_sha256'],
                         public_definition(self.job)['definition_sha256'])

    def test_modified_authority_manifest_and_wrong_uid_fail_closed(self):
        catalogue = self.manager.catalogue()
        self.manifest_path.write_bytes(encoded(dict(self.manifest, jobs=[])))
        with self.assertRaises(ValueError):
            catalogue.row(self.job['id'])
        self.manifest_path.write_bytes(encoded(self.manifest))
        preparation = self.prepare()
        with patch('coordination.github_work.os.getuid', return_value=os.getuid()+1):
            with self.assertRaises(ValueError):
                self.manager.claim(preparation['proof_sha256'])

    def test_full_cas_assignment_native_completion_reaches_board_without_private_text(self):
        from test_github_assignments import AtomicGitHub
        from coordination.github_assignments_v2 import Assignments
        from coordination.assignment_progress import requests
        import source_job_board
        import acquisition
        github = AtomicGitHub()
        store = Assignments(github, self.manager.catalogue().catalogue, self.manager.guard)
        store.initialize(dict(schema='kuina-assignment-migration-v1', complete=True,
            source_sha256='a'*64, catalogue_generation=self.fixture.generation, records=[], receipts=[]))
        catalogue = dict(generation=self.fixture.generation, batches=catalogue_rows(self.manifest))
        definitions = dict(schema=source_job_board.DEFINITION_SCHEMA, jobs=[public_definition(self.job)])
        def board(progress=None):
            ledger = store.snapshot()['ledger']
            return source_job_board.snapshot(definitions, self.sources, catalogue, ledger,
                                              self.job['confirmed_at'], progress)
        self.assertEqual(board()['jobs'][0]['state'], 'open')
        store.assign(self.job['id'], 'seann', 42, 'Alice')
        self.assertEqual(board()['jobs'][0]['stage'], 'reserved')
        # A second participant cannot take an already confirmed assignment.
        result = store.assign(self.job['id'], 'juan', 44, 'Bob')
        self.assertEqual(result['status'], 'rejected')
        preparation = self.prepare()
        result = store.set_working(self.job['id'], 'seann', 42, preparation['proof_sha256'],
                                   author='Alice', request_issue=43)
        observed = store.snapshot()
        self.manager.authorize(dict(schema='kuina-github-working-authorization-v1',
            batch_id=self.job['id'], person='seann', assignment_issue=42,
            proof_sha256=preparation['proof_sha256'], ledger_sha=observed['ledger_sha'], working_request_issue=43))
        self.manager.claim(preparation['proof_sha256'])
        self.manager.report(self.job['id'], 'seann', 'completed', 'SECRET /private/evidence')
        progress = self.manager.progress(requests(observed['ledger']))
        completed = board(progress)
        self.assertEqual(completed['jobs'][0]['state'], 'finished')
        self.assertEqual(completed['jobs'][0]['assignee'], 'seann')
        public = acquisition.render(self.sources, completed)
        self.assertNotIn('SECRET', public)
        self.assertNotIn('/private/evidence', public)
        self.assertNotIn('"uid"', public)
        self.assertIn('Confirmed free-source jobs', public)
        self.assertIn('source-jobs-data', public)
        self.assertEqual(store.snapshot()['ledger'], observed['ledger'])
        # Stale or fabricated private proof must retain permanent ownership.
        bad = copy.deepcopy(progress)
        bad['records'][0]['preparation_sha256'] = '0'*64
        self.assertEqual(board(bad)['jobs'][0]['state'], 'in_progress')


if __name__ == '__main__':
    unittest.main()

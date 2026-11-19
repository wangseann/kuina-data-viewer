import json
import os
import unittest
from unittest.mock import patch

import test_github_private as fixtures
from coordination.github_work import WorkProtocol


class WorkProtocolTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.PrivateCatalogueTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.catalogue = fixture.catalogue
        self.catalogue.fence_legacy_starts()
        self.batch = fixture.batch_id
        self.protocol = WorkProtocol(self.catalogue)

    def prepare(self):
        return self.protocol.prepare(self.batch, 'seann', 42)

    def authorization(self, proof):
        return dict(schema='kuina-github-working-authorization-v1', batch_id=self.batch,
                    person='seann', assignment_issue=42, proof_sha256=proof['proof_sha256'],
                    ledger_sha='a' * 40, working_request_issue=43)

    def test_preparation_is_not_a_worker_claim_or_assignment(self):
        result = self.prepare()
        self.assertEqual(set(result), {'schema', 'batch_id', 'person', 'assignment_issue', 'proof_sha256'})
        self.assertFalse((self.catalogue.legacy.root / 'work-claims' / self.batch).exists())
        self.assertNotIn('uid', json.dumps(result))
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.protocol.claim(result['proof_sha256'])

    def test_claim_requires_matching_observed_github_working_authorization(self):
        result = self.prepare()
        authorization = self.authorization(result)
        self.protocol.authorize(authorization)
        owner = self.protocol.claim(result['proof_sha256'])
        self.assertEqual(owner['uid'], os.getuid())
        self.assertEqual(owner['person'], 'seann')
        with self.assertRaises(FileExistsError):
            self.protocol.claim(result['proof_sha256'])
        self.assertEqual(self.protocol.authorize(authorization)['status'], 'already_authorized')

    def test_changed_person_assignment_and_proof_are_rejected(self):
        result = self.prepare()
        for key, value in [('person', 'emily'), ('assignment_issue', 44), ('proof_sha256', 'b' * 64)]:
            record = self.authorization(result)
            record[key] = value
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.protocol.authorize(record)
        self.assertFalse((self.catalogue.legacy.root / 'work-claims' / self.batch).exists())

    def test_unrelated_github_update_does_not_replace_a_valid_private_permit(self):
        result = self.prepare()
        authorization = self.authorization(result)
        self.protocol.authorize(authorization)
        path = self.protocol.authorization_path(self.batch)
        original = path.read_bytes()
        authorization['ledger_sha'] = 'b' * 40
        self.assertEqual(self.protocol.authorize(authorization)['status'], 'already_authorized')
        self.assertEqual(path.read_bytes(), original)

    def test_only_coordinator_can_authorize_and_only_token_uid_can_claim(self):
        result = self.prepare()
        with patch('coordination.github_work.os.getuid', return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                self.protocol.authorize(self.authorization(result))
        self.protocol.authorize(self.authorization(result))
        with patch('coordination.github_work.os.getuid', return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                self.protocol.claim(result['proof_sha256'])

    def test_working_guard_binds_exact_private_preparation(self):
        result = self.prepare()
        self.assertEqual(self.protocol.verify(self.batch, 'seann', 42, result['proof_sha256'])['person'], 'seann')
        with self.assertRaises(ValueError):
            self.protocol.verify(self.batch, 'emily', 42, result['proof_sha256'])
        assignment = dict(batch_id=self.batch, person='seann', assignment_issue=42)
        guard = self.catalogue.guard(self.batch, 'working', assignment, result['proof_sha256'])
        self.assertEqual(guard['state'], 'clear')
        self.assertEqual(guard['proof_sha256'], result['proof_sha256'])


if __name__ == '__main__':
    unittest.main()

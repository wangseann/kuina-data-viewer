import json
import unittest

import test_github_assignments as fixtures
from coordination.github_claims import NativeFailure
from coordination.github_backend import AuthorityBackend


class PrivateBridge:
    def __init__(self, store):
        self.store = store
        self.permits = []
        self.fail = False

    def command(self, command, *arguments):
        assert command == 'authorize-github-work'
        authorization = json.loads(arguments[1])
        observed = self.store.snapshot()
        assert authorization['ledger_sha'] == observed['ledger_sha']
        assert observed['ledger']['assignments'][fixtures.B]['status'] == 'active'
        self.permits.append(authorization)
        if self.fail:
            raise NativeFailure('private permit unavailable')
        return dict(status='authorized', proof_sha256=fixtures.P)


class AuthorityBackendTests(unittest.TestCase):
    def setUp(self):
        self.github = fixtures.AtomicGitHub()
        self.store = fixtures.Assignments(self.github, fixtures.catalogue, fixtures.guard, clock=lambda: fixtures.NOW)
        self.store.initialize(fixtures.migration())
        self.native = PrivateBridge(self.store)
        self.backend = AuthorityBackend(self.store, self.native)
        self.store.assign(fixtures.B, 'seann', 1, 'alice')

    def test_working_is_saved_in_github_before_private_execution_permit(self):
        result = self.backend.start(fixtures.B, 'seann', 'alice', 2, 1, fixtures.P)
        self.assertEqual(result['status'], 'started')
        self.assertEqual(len(self.native.permits), 1)
        self.assertEqual(self.native.permits[0]['working_request_issue'], 2)

    def test_private_permit_failure_cannot_release_or_repeat_the_github_start(self):
        self.native.fail = True
        with self.assertRaises(NativeFailure):
            self.backend.start(fixtures.B, 'seann', 'alice', 2, 1, fixtures.P)
        writes = self.github.puts
        self.native.fail = False
        self.assertEqual(self.backend.start(fixtures.B, 'seann', 'alice', 2, 1, fixtures.P)['status'], 'started')
        self.assertEqual(self.github.puts, writes)
        self.assertEqual(self.store.status(fixtures.B)['status'], 'active')

    def test_changed_request_cannot_create_a_private_execution_permit(self):
        with self.assertRaises(NativeFailure):
            self.backend.start(fixtures.B, 'emily', 'bob', 2, 1, fixtures.P)
        self.assertEqual(self.native.permits, [])
        self.assertEqual(self.store.status(fixtures.B)['status'], 'assigned')

    def test_original_imported_reservation_uses_explicit_resume_protocol(self):
        from coordination.github_assignments_v2 import Assignments
        github = fixtures.AtomicGitHub()
        store = Assignments(github, fixtures.catalogue, fixtures.guard, clock=lambda: fixtures.NOW)
        original = dict(fixtures.imported('assigned'), author='alice', assignment_issue=1)
        store.initialize(fixtures.migration([original]))
        native = PrivateBridge(store)
        backend = AuthorityBackend(store, native)
        result = backend.start(fixtures.B, 'seann', 'alice', 2, 1, fixtures.P)
        self.assertEqual(result['status'], 'started')
        self.assertEqual(store.snapshot()['ledger']['assignments'][fixtures.B]['origin'], 'migration')
        self.assertEqual(len(native.permits), 1)


if __name__ == '__main__':
    unittest.main()

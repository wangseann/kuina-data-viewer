"""Bridge permanent GitHub assignments to private execution permits."""
import json

from coordination.github_claims import NativeFailure


class AuthorityBackend:
    requires_receipt = True

    def __init__(self, store, native):
        self.store, self.native = store, native

    def status(self, task_id):
        return self.store.status(task_id)

    def request_status(self, task_id, number):
        return self.store.request_status(task_id, number)

    def assign(self, task_id, person, number, author):
        return self.store.assign(task_id, person, number, author)

    def release(self, task_id, person, author, number, assignment_issue, coordinator=False):
        return self.store.release(task_id, person, author, number, assignment_issue, coordinator)

    def start(self, task_id, person, author, number, assignment_issue, proof_sha256):
        previous = self.store.snapshot()['ledger']['assignments'].get(task_id)
        if previous is not None and previous['origin'] == 'migration':
            self.store.resume_imported(task_id, person, assignment_issue, proof_sha256, author, number)
        else:
            self.store.set_working(task_id, person, assignment_issue, proof_sha256,
                                   author=author, request_issue=number)
        receipt = self.store.request_status(task_id, number, action='working', person=person,
                                           author=author, assignment_issue=assignment_issue,
                                           proof_sha256=proof_sha256)
        if receipt is None or receipt['status'] != 'started':
            raise NativeFailure('GitHub has not confirmed this work start.')
        snapshot = self.store.snapshot()
        current = snapshot['ledger']['assignments'].get(task_id)
        if (current is None or current['status'] != 'active' or current['person'] != person or
                current['assignment_issue'] != assignment_issue or
                current['work_proof_sha256'] != proof_sha256 or current['working_request_issue'] != number):
            raise NativeFailure('The observed working reservation does not match this request.')
        authorization = dict(schema='kuina-github-working-authorization-v1', batch_id=task_id,
                             person=person, assignment_issue=assignment_issue, proof_sha256=proof_sha256,
                             ledger_sha=snapshot['ledger_sha'], working_request_issue=number)
        result = self.native.command('authorize-github-work', '--authorization',
                                     json.dumps(authorization, separators=(',', ':')))
        if (type(result) is not dict or set(result) != {'status', 'proof_sha256'} or
                result['status'] not in ('authorized', 'already_authorized') or result['proof_sha256'] != proof_sha256):
            raise NativeFailure('The private execution permit has not been verified.')
        return receipt

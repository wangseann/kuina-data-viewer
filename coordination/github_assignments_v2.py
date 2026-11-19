"""Explicit continuation of protected, unstarted imported reservations.

Normal assignment/release/start behavior is inherited unchanged from V1. Legacy
starts keep every fence and require a bound private token plus observed CAS start
receipt before a separate private permit may be issued.
"""
import copy

from .github_assignments import (
    Assignments as _V1, Unavailable, actor, batch, digest, error_status, integer,
    require, stamp,
)
from .github_claims import PEOPLE


class Assignments(_V1):
    supports_imported_resume = True

    @staticmethod
    def _validate_started(ledger):
        # A resumed import has no new assign receipt: its original reservation
        # remains authoritative. Its working receipt must nevertheless persist.
        for item in ledger['assignments'].values():
            if item['working_request_issue'] is None:
                continue
            receipt = ledger['receipts'].get(str(item['working_request_issue']))
            if not (item['status'] == 'active' and receipt is not None and
                    receipt['action'] == 'working' and receipt['status'] == 'started' and
                    receipt['batch_id'] == item['batch_id'] and receipt['person'] == item['person'] and
                    receipt['assignment_issue'] == item['assignment_issue'] and
                    receipt['proof_sha256'] == item['work_proof_sha256'] and
                    receipt['definition_sha256'] == item['definition_sha256'] and
                    receipt['catalogue_generation'] == item['catalogue_generation']):
                raise Unavailable('Protected working marker and start receipt disagree.')
        for receipt in ledger['receipts'].values():
            if receipt['origin'] != 'github' or receipt['action'] != 'working' or receipt['status'] != 'started':
                continue
            item = ledger['assignments'].get(receipt['batch_id'])
            if not (item is not None and item['status'] == 'active' and
                    item['working_request_issue'] == receipt['request_issue'] and
                    item['work_proof_sha256'] == receipt['proof_sha256']):
                raise Unavailable('A confirmed start cannot disappear from current authority.')

    def _read(self, missing=False):
        result = super()._read(missing=missing)
        if result is not None:
            self._validate_started(result[1])
        return result

    def _encode(self, ledger):
        raw = super()._encode(ledger)
        self._validate_started(ledger)
        return raw

    def resume_imported(self, batch_id, person, assignment_issue, proof_sha256, author, request_issue):
        batch(batch_id)
        require(person in PEOPLE and integer(assignment_issue) and digest(proof_sha256) and integer(request_issue))
        actor(author)
        author = author.casefold()
        for attempt in range(self.max_attempts):
            sha, ledger = self._read()
            previous = ledger['receipts'].get(str(request_issue))
            if previous is not None:
                self._binding(previous, batch_id, 'working', person, author, assignment_issue, proof_sha256)
                current = ledger['assignments'].get(batch_id)
                if not (previous['status'] == 'started' and current is not None and
                        current['origin'] == 'migration' and current['status'] == 'active' and
                        current['person'] == person and current['assignment_issue'] == assignment_issue and
                        current['work_proof_sha256'] == proof_sha256 and current['working_request_issue'] == request_issue):
                    raise Unavailable('This receipt does not authorize the protected imported continuation.')
                return self._result(previous)
            current = ledger['assignments'].get(batch_id)
            if not (current is not None and current['origin'] == 'migration' and current['status'] == 'assigned' and
                    current['person'] == person and current['assignment_issue'] == assignment_issue and
                    current['author'] is not None and current['author'].casefold() == author and
                    current['work_proof_sha256'] is None and current['working_request_issue'] is None):
                raise Unavailable('Only the unchanged original imported reservation can resume.')
            context = self._catalogue(batch_id)
            if (context['definition_sha256'], context['generation']) != (current['definition_sha256'], current['catalogue_generation']):
                raise Unavailable('Imported reservation definition or generation changed.')
            guarded = self._guard(batch_id, 'working', current, proof_sha256)
            if guarded['state'] != 'clear':
                raise Unavailable('An existing or uncertain private worker cannot be started again.')
            if self._catalogue(batch_id) != context:
                raise Unavailable('Frozen imported catalogue changed during continuation.')
            now = self.clock()
            stamp(now)
            updated = copy.deepcopy(ledger)
            updated['assignments'][batch_id].update(status='active', work_proof_sha256=proof_sha256,
                                                    working_request_issue=request_issue, updated_at=now)
            receipt = dict(request_issue=request_issue, batch_id=batch_id, action='working', person=person,
                           author=author, assignment_issue=assignment_issue, proof_sha256=proof_sha256,
                           status='started', recorded_at=now, definition_sha256=current['definition_sha256'],
                           catalogue_generation=current['catalogue_generation'], origin='github')
            updated['receipts'][str(request_issue)] = receipt
            error = None
            try:
                self._put(sha, updated)
            except Exception as failure:
                error = failure
            _, observed = self._read()
            item = observed['receipts'].get(str(request_issue))
            if item is not None:
                self._binding(item, batch_id, 'working', person, author, assignment_issue, proof_sha256)
                # _read validated the permanent active marker and its receipt.
                if item['status'] != 'started' or observed['assignments'][batch_id]['origin'] != 'migration':
                    raise Unavailable('Imported continuation was not observed.')
                return self._result(item)
            if error is not None and error_status(error) == 409 and attempt + 1 < self.max_attempts:
                continue
            raise Unavailable('Imported start is unconfirmed; reconcile its exact issue before retrying.')
        raise Unavailable('Imported continuation CAS retry bound reached.')

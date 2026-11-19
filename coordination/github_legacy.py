"""Resume imported reservations without unlocking any legacy task fence.

The randomized reservation context lives beside the generic preparation. Its
hash occupies the token's opaque nonce, binding the full original Native current
record without changing the generic preparation or authorization schemas.
"""
import copy
import os
import re
import secrets
import stat

from coordination.github_assignments import record as validate_assignment
from coordination.github_private import PrivateCatalogue
from coordination.github_work import WorkProtocol, encoded, exclusive_write, sha
from coordination.task_manager import PEOPLE, digest, instant, now, require
from coordination.unique_queue import closed, file_bytes, parse, safe_path


class LegacyCatalogue(PrivateCatalogue):
    def fenced_task(self, task_id):
        self.check_generation()
        require(self.legacy.self_service(), 'Legacy self-service mode required')
        task = self.legacy.task(task_id)
        require(self.unique_freeze() and self.queue.valid_fence(task, self.config),
                'Matching migration freeze and legacy fence required')
        return task

    def legacy_task(self, task_id):
        task = self.fenced_task(task_id)
        reservation = self.legacy.reservation(task)
        worker = self.legacy.work_claim_record(task)
        require((reservation and reservation['current']) or worker,
                'Only an existing legacy reservation or worker may be resolved')
        return task

    def native_state(self, batch_id):
        task = self.legacy_task(batch_id)
        reservation = self.legacy.reservation(task)
        current = copy.deepcopy(reservation['current']) if reservation else None
        worker = self.legacy.work_claim_record(task)
        status, _ = self.legacy.state(task)
        return task, current, worker, status

    def row(self, batch_id):
        if batch_id in self.rows:
            return super().row(batch_id)
        task = self.legacy_task(batch_id)
        return dict(id=task['id'], category=task['category'], file=dict(sha256=digest(task)))

    def catalogue(self, batch_id):
        if batch_id in self.rows:
            return super().catalogue(batch_id)
        row = self.row(batch_id)
        return dict(schema='kuina-assignment-catalogue-v1', batch_id=batch_id,
                    generation=self.generation, definition_sha256=row['file']['sha256'],
                    assignment_enabled=False)

    def guard(self, batch_id, action, assignment, proof_sha256=None):
        if batch_id in self.rows:
            return super().guard(batch_id, action, assignment, proof_sha256)
        require(action in ('assign', 'release', 'working'), 'Unknown guard action')
        task, current, worker, status = self.native_state(batch_id)
        result = dict(schema='kuina-assignment-guard-v1',
                      state='working' if worker else 'blocked', proof_sha256=None)
        if action == 'release':
            require(proof_sha256 is None, 'Release cannot use a work proof')
            return result  # Imported reservations are never released here.
        if worker or current is None or status != 'assigned':
            return result
        if action == 'assign':
            require(assignment is None and proof_sha256 is None,
                    'Legacy guard is preparation-only, not a new assignment')
            result.update(state='clear', proof_sha256=sha(encoded(dict(
                generation=self.generation, definition_sha256=digest(task), reservation=current))))
            return result
        validate_assignment(assignment)
        require(assignment['batch_id'] == batch_id and assignment['origin'] == 'migration'
                and assignment['status'] == 'assigned' and assignment['person'] == current['person']
                and isinstance(assignment['author'], str)
                and assignment['author'].casefold() == current['github_author'].casefold()
                and assignment['assignment_issue'] == current['issue']
                and assignment['definition_sha256'] == digest(task)
                and assignment['catalogue_generation'] == self.generation
                and assignment['work_proof_sha256'] is None and assignment['working_request_issue'] is None,
                'Exact original imported reservation required')
        CombinedWorkProtocol(self).verify(batch_id, current['person'], current['issue'], proof_sha256)
        result.update(state='clear', proof_sha256=proof_sha256)
        return result


class CombinedWorkProtocol(WorkProtocol):
    def context_path(self, proof_sha256):
        self.preparation_path(proof_sha256)  # Reuse the closed SHA validation.
        return self.hub.shared_directory('proposals') / ('github-legacy-context-' + proof_sha256 + '.json')

    @staticmethod
    def private_bytes(path, owner):
        raw = file_bytes(path, 8192, owner)
        require(stat.S_IMODE(path.stat().st_mode) == 0o644, 'Private preparation/context mode must be 0644')
        return raw

    def prepare(self, batch_id, person, assignment_issue):
        if batch_id in self.catalogue.rows:
            return super().prepare(batch_id, person, assignment_issue)
        require(person in PEOPLE and type(assignment_issue) is int and assignment_issue > 0,
                'Participant and confirmed assignment issue required')
        task, current, worker, status = self.catalogue.native_state(batch_id)
        require(current and current['person'] == person and current['issue'] == assignment_issue
                and worker is None and status == 'assigned', 'Exact unstarted Native reservation required')
        require(self.catalogue.guard(batch_id, 'assign', None)['state'] == 'clear',
                'Legacy reservation cannot prepare')
        context = dict(schema='kuina-private-legacy-reservation-context-v1', batch_id=batch_id,
                       generation=self.catalogue.generation, definition_sha256=digest(task), uid=os.getuid(),
                       reservation=current, nonce=secrets.token_hex(32))
        context_raw = encoded(context)
        value = dict(schema='kuina-private-github-work-preparation-v1', batch_id=batch_id,
                     generation=self.catalogue.generation, definition_sha256=digest(task), person=person,
                     uid=os.getuid(), assignment_issue=assignment_issue, prepared_at=now(), nonce=sha(context_raw))
        raw = encoded(value)
        proof_sha256 = sha(raw)
        exclusive_write(self.context_path(proof_sha256), context_raw)
        exclusive_write(self.preparation_path(proof_sha256), raw)
        self.verify(batch_id, person, assignment_issue, proof_sha256)
        return dict(schema='kuina-public-work-preparation-v1', batch_id=batch_id, person=person,
                    assignment_issue=assignment_issue, proof_sha256=proof_sha256)

    def bound_context(self, prepared, proof_sha256):
        raw = self.private_bytes(self.context_path(proof_sha256), prepared['uid'])
        require(sha(raw) == prepared['nonce'], 'Original Native context hash changed')
        context = parse(raw)
        closed(context, ('schema', 'batch_id', 'generation', 'definition_sha256', 'uid', 'reservation', 'nonce'))
        require(context['schema'] == 'kuina-private-legacy-reservation-context-v1'
                and context['batch_id'] == prepared['batch_id']
                and context['generation'] == prepared['generation']
                and context['definition_sha256'] == prepared['definition_sha256']
                and type(context['uid']) is int and context['uid'] == prepared['uid']
                and isinstance(context['nonce'], str) and re.fullmatch('[0-9a-f]{64}', context['nonce']),
                'Legacy context does not match private preparation')
        return context

    def current_context(self, prepared, context):
        task = self.catalogue.fenced_task(prepared['batch_id'])
        record = self.hub.reservation(task)
        current = record['current'] if record else None
        require(digest(task) == prepared['definition_sha256'] and current is not None
                and current == context['reservation'] and current['person'] == prepared['person']
                and current['issue'] == prepared['assignment_issue'], 'Original Native reservation changed')
        return task, current

    def observed_permit(self, prepared, proof_sha256):
        raw = file_bytes(self.authorization_path(prepared['batch_id']), 8192, self.hub.root.stat().st_uid)
        value = parse(raw)
        closed(value, ('schema', 'batch_id', 'person', 'assignment_issue', 'proof_sha256',
                       'ledger_sha', 'working_request_issue'))
        require(value['schema'] == 'kuina-github-working-authorization-v1'
                and value['batch_id'] == prepared['batch_id'] and value['person'] == prepared['person']
                and type(value['assignment_issue']) is int and value['assignment_issue'] == prepared['assignment_issue']
                and value['proof_sha256'] == proof_sha256 and isinstance(value['ledger_sha'], str)
                and re.fullmatch('[0-9a-f]{40}', value['ledger_sha'])
                and type(value['working_request_issue']) is int and value['working_request_issue'] > 0,
                'Exact observed GitHub working permit required')
        return value

    def verify(self, batch_id, person, assignment_issue, proof_sha256):
        if batch_id in self.catalogue.rows:
            return super().verify(batch_id, person, assignment_issue, proof_sha256)
        prepared = super().verify(batch_id, person, assignment_issue, proof_sha256)
        self.private_bytes(self.preparation_path(proof_sha256), prepared['uid'])
        context = self.bound_context(prepared, proof_sha256)
        task, current = self.current_context(prepared, context)
        worker = self.hub.work_claim_record(task)
        if worker:
            owner = worker[1]
            require(owner['uid'] == prepared['uid'] and owner['person'] == person
                    and owner['task_sha256'] == prepared['definition_sha256']
                    and instant(owner['claimed_at']) >= instant(prepared['prepared_at'])
                    and instant(owner['claimed_at']) >= instant(current['assigned_at']),
                    'Existing legacy worker does not match this preparation')
            self.observed_permit(prepared, proof_sha256)
        else:
            require(self.hub.state(task)[0] == 'assigned', 'Unstarted Native reservation required')
        return prepared

    def claim(self, proof_sha256):
        token = parse(file_bytes(self.preparation_path(proof_sha256), 8192))
        if token['batch_id'] in self.catalogue.rows:
            return super().claim(proof_sha256)
        prepared = self.verify(token['batch_id'], token['person'], token['assignment_issue'], proof_sha256)
        require(prepared['uid'] == os.getuid(), 'Only preparation UID may start this legacy worker')
        self.observed_permit(prepared, proof_sha256)
        context = self.bound_context(prepared, proof_sha256)
        task, current = self.current_context(prepared, context)
        require(self.hub.work_claim_record(task) is None, 'Actual legacy worker already exists')
        path = safe_path(self.hub.shared_directory('work-claims') / task['id'])
        path.mkdir(mode=0o755)  # Exclusive start; an uncertain directory is retained.
        os.chmod(path, 0o755)
        self.current_context(prepared, context)
        owner = dict(uid=os.getuid(), person=prepared['person'], task_sha256=digest(task), claimed_at=now())
        require(instant(owner['claimed_at']) >= instant(prepared['prepared_at'])
                and instant(owner['claimed_at']) >= instant(current['assigned_at']), 'Legacy claim predates its proof')
        exclusive_write(path / 'owner.json', encoded(owner))
        self.verify(task['id'], prepared['person'], prepared['assignment_issue'], proof_sha256)
        return owner

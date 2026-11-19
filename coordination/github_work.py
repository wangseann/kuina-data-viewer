"""Private worker preparations; GitHub working records authorize actual starts.

The broker may authorize only after observing GitHub's committed working record.
An authorization is a private execution permit, never an assignment authority.
Lost private files therefore cannot release the permanent GitHub reservation.
"""
import hashlib
import json
import os
import re
import secrets

from coordination.task_manager import PEOPLE, instant, now, require
from coordination.unique_queue import closed, file_bytes, parse, safe_path


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exclusive_write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fchmod(stream.fileno(), 0o644)
        os.fsync(stream.fileno())


class WorkProtocol:
    def __init__(self, catalogue):
        self.catalogue = catalogue
        self.hub = catalogue.legacy

    def preparation_path(self, proof_sha256):
        require(isinstance(proof_sha256, str) and re.fullmatch('[0-9a-f]{64}', proof_sha256),
                'Exact preparation SHA256 required')
        return self.hub.shared_directory('proposals') / ('github-work-' + proof_sha256 + '.json')

    def prepare(self, batch_id, person, assignment_issue):
        require(person in PEOPLE and type(assignment_issue) is int and assignment_issue > 0,
                'Participant and confirmed assignment issue required')
        row = self.catalogue.row(batch_id)
        require(self.catalogue.guard(batch_id, 'assign', None)['state'] == 'clear',
                'Legacy overlap or incomplete migration prevents preparation')
        require(not (self.hub.shared_directory('work-claims') / batch_id).exists(),
                'Actual worker already exists; continue its original claim')
        value = dict(schema='kuina-private-github-work-preparation-v1', batch_id=batch_id,
                     generation=self.catalogue.generation, definition_sha256=row['file']['sha256'],
                     person=person, uid=os.getuid(), assignment_issue=assignment_issue,
                     prepared_at=now(), nonce=secrets.token_hex(32))
        raw = encoded(value)
        proof_sha256 = sha(raw)
        exclusive_write(self.preparation_path(proof_sha256), raw)
        self.verify(batch_id, person, assignment_issue, proof_sha256)
        return dict(schema='kuina-public-work-preparation-v1', batch_id=batch_id, person=person,
                    assignment_issue=assignment_issue, proof_sha256=proof_sha256)

    def verify(self, batch_id, person, assignment_issue, proof_sha256):
        path = safe_path(self.preparation_path(proof_sha256))
        info = path.stat()
        raw = file_bytes(path, 8192, info.st_uid)
        require(sha(raw) == proof_sha256, 'Private preparation changed')
        value = parse(raw)
        closed(value, ('schema', 'batch_id', 'generation', 'definition_sha256', 'person',
                       'uid', 'assignment_issue', 'prepared_at', 'nonce'))
        row = self.catalogue.row(batch_id)
        require(value['schema'] == 'kuina-private-github-work-preparation-v1' and
                value['batch_id'] == batch_id and value['generation'] == self.catalogue.generation and
                value['definition_sha256'] == row['file']['sha256'] and
                value['person'] == person and person in PEOPLE and
                type(value['uid']) is int and value['uid'] == info.st_uid and
                type(value['assignment_issue']) is int and value['assignment_issue'] == assignment_issue and
                type(assignment_issue) is int and assignment_issue > 0,
                'Private preparation does not match the confirmed assignment')
        require(isinstance(value['nonce'], str) and re.fullmatch('[0-9a-f]{64}', value['nonce']),
                'Invalid preparation nonce')
        require(instant(value['prepared_at']) <= instant(now()), 'Invalid preparation timestamp')
        return value

    def authorization_path(self, batch_id):
        self.catalogue.row(batch_id)
        parent = self.hub.root / 'assignments'
        self.hub.protected(parent)
        return parent / ('github-working-' + batch_id + '.json')

    def validate_authorization(self, value):
        closed(value, ('schema', 'batch_id', 'person', 'assignment_issue', 'proof_sha256',
                       'ledger_sha', 'working_request_issue'))
        require(value['schema'] == 'kuina-github-working-authorization-v1' and
                isinstance(value['ledger_sha'], str) and re.fullmatch('[0-9a-f]{40}', value['ledger_sha']) and
                type(value['working_request_issue']) is int and value['working_request_issue'] > 0,
                'Observed GitHub working commit and request required')
        return self.verify(value['batch_id'], value['person'], value['assignment_issue'], value['proof_sha256'])

    def authorize(self, value):
        require(os.getuid() == self.hub.root.stat().st_uid, 'Coordinator UID required')
        self.validate_authorization(value)
        path = self.authorization_path(value['batch_id'])
        raw = encoded(value)
        try:
            exclusive_write(path, raw)
        except FileExistsError:
            existing = parse(file_bytes(path, 8192, os.getuid()))
            self.validate_authorization(existing)
            # Other assignments change the ledger blob SHA. Retain the first
            # observed working commit and its immutable private permit.
            require({k: v for k, v in existing.items() if k != 'ledger_sha'} ==
                    {k: v for k, v in value.items() if k != 'ledger_sha'},
                    'A different working authorization exists; reconcile without overwrite')
            return dict(status='already_authorized', proof_sha256=value['proof_sha256'])
        require(file_bytes(path, 8192, os.getuid()) == raw, 'Working permit not observed')
        return dict(status='authorized', proof_sha256=value['proof_sha256'])

    def claim(self, proof_sha256):
        token = parse(file_bytes(self.preparation_path(proof_sha256), 8192))
        prepared = self.verify(token['batch_id'], token['person'], token['assignment_issue'], proof_sha256)
        require(prepared['uid'] == os.getuid(), 'Only preparation UID may start this worker')
        authorization_raw = file_bytes(self.authorization_path(prepared['batch_id']), 8192,
                                       self.hub.root.stat().st_uid)
        authorization = parse(authorization_raw)
        self.validate_authorization(authorization)
        require(authorization['proof_sha256'] == proof_sha256,
                'Working authorization belongs to a different private preparation')
        require(self.catalogue.guard(prepared['batch_id'], 'assign', None)['state'] == 'clear',
                'Legacy work overlaps this scope')
        path = self.hub.shared_directory('work-claims') / prepared['batch_id']
        path.mkdir(mode=0o755)  # One actual start, never repeated after an uncertain result.
        os.chmod(path, 0o755)
        owner = dict(schema='kuina-github-private-worker-v1', uid=os.getuid(), person=prepared['person'],
                     task_sha256=prepared['definition_sha256'], claimed_at=now(),
                     preparation_sha256=proof_sha256, authorization_sha256=sha(authorization_raw))
        exclusive_write(path / 'owner.json', encoded(owner))
        return owner

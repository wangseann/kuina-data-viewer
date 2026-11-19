"""Permanent metadata-only GitHub reservations, using one Contents API CAS file.

Assignments and immutable issue receipts commit in the same blob. Mutators always
read fresh authority and confirm only an observed receipt/working marker.
"""
import base64
import copy
import hashlib
from datetime import datetime, timezone
import json
import re

from .github_claims import LOGIN, PEOPLE, TASK_ID, NativeFailure

SCHEMA = 'kuina-github-assignments-v1'
MAX_BYTES = 512 * 1024
MAX_ENTRIES = 20000
HASH = re.compile(r'[0-9a-f]{64}')
RECORD_FIELDS = {'batch_id', 'person', 'author', 'assignment_issue', 'status',
                 'definition_sha256', 'catalogue_generation', 'created_at',
                 'updated_at', 'origin', 'work_proof_sha256', 'working_request_issue'}
RECEIPT_FIELDS = {'request_issue', 'batch_id', 'action', 'person', 'author',
                  'assignment_issue', 'proof_sha256', 'status', 'recorded_at',
                  'definition_sha256', 'catalogue_generation', 'origin'}


class InvalidAssignment(ValueError):
    """A closed metadata contract was not satisfied; content is not echoed."""


class Unavailable(NativeFailure):
    """Keep requests open; missing proof is never availability."""


def require(value, message='Invalid assignment metadata.'):
    if not value:
        raise InvalidAssignment(message)


def integer(value):
    return type(value) is int and 0 < value <= 2147483647


def digest(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def stamp(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.]\d{1,6})?(?:Z|[+]00:00)', value) is not None)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0)
    except (ValueError, TypeError, AttributeError):
        raise InvalidAssignment('Invalid UTC timestamp.') from None
    return parsed


def batch(value):
    require(isinstance(value, str) and TASK_ID.fullmatch(value) is not None)


def actor(value, nullable=False):
    require(nullable and value is None or isinstance(value, str) and LOGIN.fullmatch(value) is not None)


def record(value):
    require(type(value) is dict and set(value) == RECORD_FIELDS)
    batch(value['batch_id'])
    require(value['origin'] in ('github', 'migration'))
    require(value['person'] in PEOPLE or value['origin'] == 'migration' and value['person'] is None)
    actor(value['author'], nullable=value['origin'] == 'migration')
    require(integer(value['assignment_issue']) or value['origin'] == 'migration' and value['assignment_issue'] is None)
    require(value['status'] in ('assigned', 'active', 'blocked', 'awaiting_verification', 'verified'))
    require(digest(value['definition_sha256']) and digest(value['catalogue_generation']))
    require(value['work_proof_sha256'] is None or digest(value['work_proof_sha256']))
    require(value['working_request_issue'] is None or integer(value['working_request_issue']))
    require(stamp(value['created_at']) <= stamp(value['updated_at']))
    if value['origin'] == 'github':
        require(value['status'] in ('assigned', 'active'))
        require((value['status'] == 'assigned') == (value['work_proof_sha256'] is None))
        if value['status'] == 'assigned':
            require(value['working_request_issue'] is None)


def receipt(value):
    require(type(value) is dict and set(value) == RECEIPT_FIELDS)
    batch(value['batch_id'])
    require(integer(value['request_issue']) and value['action'] in ('assign', 'release', 'working'))
    require(value['person'] in PEOPLE and value['origin'] in ('github', 'migration'))
    actor(value['author'], nullable=value['origin'] == 'migration')
    require(value['status'] in ({'assign': ('confirmed', 'rejected'),
                                'release': ('released', 'rejected'),
                                'working': ('started', 'rejected')}[value['action']]))
    if value['action'] == 'assign':
        require(value['assignment_issue'] is None and value['proof_sha256'] is None)
    else:
        require(integer(value['assignment_issue']) or value['origin'] == 'migration' and value['assignment_issue'] is None)
        require(digest(value['proof_sha256']) if value['action'] == 'working' else value['proof_sha256'] is None)
    require(digest(value['definition_sha256']) and digest(value['catalogue_generation']))
    stamp(value['recorded_at'])


def validate_ledger(value):
    require(type(value) is dict and set(value) == {'schema', 'migration', 'assignments', 'receipts'})
    require(value['schema'] == SCHEMA)
    migration = value['migration']
    require(type(migration) is dict and set(migration) == {'complete', 'source_sha256', 'catalogue_generation'})
    require(migration['complete'] is True and digest(migration['source_sha256']) and digest(migration['catalogue_generation']))
    for name, validator in [('assignments', record), ('receipts', receipt)]:
        items = value[name]
        require(type(items) is dict and len(items) <= MAX_ENTRIES)
        for key, item in items.items():
            validator(item)
            require(key == (item['batch_id'] if name == 'assignments' else str(item['request_issue'])))
    # A missing row cannot erase a confirmed reservation. Current GitHub rows
    # must also refer to their own observed immutable assignment/start receipts.
    released = {(r['batch_id'], r['person'], r['assignment_issue'])
                for r in value['receipts'].values() if r['action'] == 'release' and r['status'] == 'released'}
    started = {(r['batch_id'], r['person'], r['assignment_issue'])
               for r in value['receipts'].values() if r['action'] == 'working' and r['status'] == 'started'}
    require(not released & started, 'Started work cannot have a release receipt.')
    for item in value['receipts'].values():
        if item['action'] != 'assign' or item['status'] != 'confirmed':
            continue
        current = value['assignments'].get(item['batch_id'])
        held = current is not None and current['assignment_issue'] == item['request_issue']
        require(held or (item['batch_id'], item['person'], item['request_issue']) in released,
                'Confirmed reservation history has no current assignment or release.')
    for item in value['assignments'].values():
        if item['origin'] != 'github':
            continue
        assigned = value['receipts'].get(str(item['assignment_issue']))
        require(assigned is not None and assigned['action'] == 'assign' and assigned['status'] == 'confirmed'
                and all(assigned[k] == item[k] for k in ('batch_id', 'person', 'author', 'definition_sha256', 'catalogue_generation')),
                'Assignment lacks its exact confirmed receipt.')
        if item['working_request_issue'] is not None:
            work = value['receipts'].get(str(item['working_request_issue']))
            require(work is not None and work['action'] == 'working' and work['status'] == 'started'
                    and work['batch_id'] == item['batch_id'] and work['person'] == item['person']
                    and work['assignment_issue'] == item['assignment_issue']
                    and work['proof_sha256'] == item['work_proof_sha256'], 'Working state lacks its exact start receipt.')
    return value


def error_status(error):
    status = getattr(error, 'status', None) or getattr(error, 'status_code', None)
    if type(status) is int:
        return status
    stderr = getattr(error, 'stderr', b'')
    if isinstance(stderr, bytes):
        stderr = stderr.decode('utf-8', 'replace')
    match = re.search(r'\bHTTP (404|409|422)\b', stderr) if isinstance(stderr, str) else None
    return int(match[1]) if match else None


class Assignments:
    requires_receipt = True

    def __init__(self, github, catalogue, private_guard, *, path='coordination/assignments.json',
                 branch='main', max_attempts=3, max_bytes=MAX_BYTES, clock=None):
        require(isinstance(path, str) and re.fullmatch(r'[A-Za-z0-9_./-]{1,180}', path) and
                not path.startswith('/') and all(x not in ('', '.', '..') for x in path.split('/')))
        require(isinstance(branch, str) and re.fullmatch(r'[A-Za-z0-9_.\/-]{1,128}', branch) and '..' not in branch)
        require(type(max_attempts) is int and 1 <= max_attempts <= 5)
        require(type(max_bytes) is int and 1024 <= max_bytes <= MAX_BYTES)
        self.github, self.catalogue, self.private_guard = github, catalogue, private_guard
        self.path, self.branch = path, branch
        self.max_attempts, self.max_bytes = max_attempts, max_bytes
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.endpoint = 'repos/' + github.repo + '/contents/' + path
        self.owner = github.owner.casefold()

    def _encode(self, ledger):
        validate_ledger(ledger)
        raw = (json.dumps(ledger, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
        if len(raw) > self.max_bytes:
            raise Unavailable('Assignment ledger capacity reached; no history was discarded.')
        return raw

    def _read(self, missing=False):
        try:
            item = self.github.api(self.endpoint, fields={'ref': self.branch})
        except Exception as error:
            if missing and error_status(error) == 404:
                return None
            raise Unavailable('GitHub assignment authority could not be read.') from None
        try:
            require(type(item) is dict and item.get('type') == 'file' and item.get('encoding') == 'base64')
            require(type(item.get('size')) is int and 0 < item['size'] <= self.max_bytes)
            require(isinstance(item.get('content'), str) and len(item['content']) <= self.max_bytes * 2)
            require(isinstance(item.get('sha'), str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', item['sha']))
            raw = base64.b64decode(''.join(item['content'].splitlines()), validate=True)
            require(len(raw) == item['size'])
            blob = b'blob ' + str(len(raw)).encode() + b'\0' + raw
            hasher = hashlib.sha1 if len(item['sha']) == 40 else hashlib.sha256
            require(hasher(blob).hexdigest() == item['sha'], 'Contents payload and CAS version disagree.')
            data = validate_ledger(json.loads(raw))
            self._encode(data)
            return item['sha'], data
        except (ValueError, TypeError, KeyError):
            raise Unavailable('GitHub assignment authority failed its closed metadata contract.') from None

    def snapshot(self):
        sha, data = self._read()
        return {'ledger_sha': sha, 'ledger': copy.deepcopy(data)}

    def _put(self, sha, ledger):
        raw = self._encode(ledger)
        fields = {'message': 'Update confirmed Kuina assignment metadata',
                  'branch': self.branch, 'content': base64.b64encode(raw).decode()}
        if sha is not None:
            fields['sha'] = sha
        self.github.api(self.endpoint, 'PUT', fields)

    def _catalogue(self, task_id):
        try:
            require(callable(self.catalogue))
            data = self.catalogue(task_id)
            require(type(data) is dict and set(data) == {'schema', 'batch_id', 'generation', 'definition_sha256', 'assignment_enabled'})
            require(data['schema'] == 'kuina-assignment-catalogue-v1' and data['batch_id'] == task_id)
            require(digest(data['generation']) and digest(data['definition_sha256']) and type(data['assignment_enabled']) is bool)
            return copy.deepcopy(data)
        except Exception:
            raise Unavailable('Frozen catalogue evidence is unavailable or invalid.') from None

    def _guard(self, task_id, action, current, proof=None):
        try:
            require(callable(self.private_guard))
            data = self.private_guard(task_id, action, copy.deepcopy(current), proof)
            require(type(data) is dict and set(data) == {'schema', 'state', 'proof_sha256'})
            require(data['schema'] == 'kuina-assignment-guard-v1' and data['state'] in ('clear', 'working', 'blocked', 'unknown'))
            require(data['proof_sha256'] is None or digest(data['proof_sha256']))
            require(data['state'] in (('clear', 'working') if action == 'working' else ('clear',)))
            require(digest(data['proof_sha256']) and (action != 'working' or data['proof_sha256'] == proof))
            return data
        except Exception:
            raise Unavailable('Private work guard is not clear; no availability or release was inferred.') from None

    def initialize(self, migration):
        require(type(migration) is dict and set(migration) == {'schema', 'complete', 'source_sha256', 'catalogue_generation', 'records', 'receipts'})
        require(migration['schema'] == 'kuina-assignment-migration-v1' and migration['complete'] is True)
        require(type(migration['records']) is list and type(migration['receipts']) is list)
        require(len(migration['records']) <= MAX_ENTRIES and len(migration['receipts']) <= MAX_ENTRIES)
        assignments, receipts, contexts = {}, {}, {}
        for item in migration['records']:
            record(item)
            require(item['origin'] == 'migration' and item['batch_id'] not in assignments)
            context = self._catalogue(item['batch_id'])
            require(item['definition_sha256'] == context['definition_sha256'] and item['catalogue_generation'] == context['generation'] == migration['catalogue_generation'])
            contexts[item['batch_id']] = context
            assignments[item['batch_id']] = copy.deepcopy(item)
        for item in migration['receipts']:
            receipt(item)
            require(item['origin'] == 'migration' and str(item['request_issue']) not in receipts)
            receipts[str(item['request_issue'])] = copy.deepcopy(item)
        ledger = dict(schema=SCHEMA, migration={k: migration[k] for k in ('complete', 'source_sha256', 'catalogue_generation')},
                      assignments=assignments, receipts=receipts)
        self._encode(ledger)
        if any(self._catalogue(k) != v for k, v in contexts.items()):
            raise Unavailable('Migration catalogue changed; no initialization was written.')
        before = self._read(missing=True)
        if before is None:
            try:
                self._put(None, ledger)
            except Exception:
                pass  # Only an observed exact migration proves initialization.
            before = self._read()
        _, observed = before
        if observed['migration'] != ledger['migration'] or any(observed['assignments'].get(k) != v for k, v in assignments.items()) or any(observed['receipts'].get(k) != v for k, v in receipts.items()):
            raise Unavailable('Existing assignment authority differs; it was not overwritten.')
        return self.snapshot()

    @staticmethod
    def _view(task_id, current, blocked=False):
        return dict(task_id=task_id, status='blocked' if blocked else current['status'] if current else 'available',
                    assignee=current['person'] if current else None,
                    assignment_issue=current['assignment_issue'] if current else None)

    def status(self, task_id):
        batch(task_id)
        _, ledger = self._read()
        current = ledger['assignments'].get(task_id)
        if current and (current['status'] != 'assigned' or current['origin'] == 'migration'):
            return self._view(task_id, current, blocked=current['status'] == 'assigned')
        try:
            context = self._catalogue(task_id)
            require(context['assignment_enabled'])
            if current:
                require(current['definition_sha256'] == context['definition_sha256'] and current['catalogue_generation'] == context['generation'])
            self._guard(task_id, 'assign', current)
        except (InvalidAssignment, Unavailable):
            return self._view(task_id, current, blocked=True)
        return self._view(task_id, current)

    @staticmethod
    def _binding(item, task_id, action, person, author, assignment_issue, proof):
        if (item['batch_id'], item['action'], item['person'], item['author'], item['assignment_issue'], item['proof_sha256']) != (task_id, action, person, author, assignment_issue, proof):
            raise Unavailable('This issue is already bound to another request.')

    def request_receipt(self, task_id, number):
        batch(task_id); require(integer(number))
        _, ledger = self._read()
        item = ledger['receipts'].get(str(number))
        if item is not None and item['batch_id'] != task_id:
            raise Unavailable('This issue belongs to another batch request.')
        return copy.deepcopy(item)

    def request_status(self, task_id, number, *, action=None, person=None, author=None, assignment_issue=None, proof_sha256=None):
        item = self.request_receipt(task_id, number)
        if item is None:
            return None
        if action is not None or person is not None or author is not None:
            require(action is not None and person is not None and author is not None)
            self._binding(item, task_id, action, person, author.casefold(), assignment_issue, proof_sha256)
        return dict(task_id=task_id, request_issue=number, action=item['action'], person=item['person'], status=item['status'])

    def assign(self, task_id, person, number, author):
        return self._request(task_id, person, number, author, 'assign', None, None, False)

    def release(self, task_id, person, author, number, assignment_issue, coordinator=False):
        return self._request(task_id, person, number, author, 'release', assignment_issue, None, coordinator)

    def set_working(self, task_id, person, assignment_issue, proof_sha256, *, author=None, request_issue=None):
        require(digest(proof_sha256) and integer(assignment_issue))
        if author is not None or request_issue is not None:
            require(author is not None and request_issue is not None)
            return self._request(task_id, person, request_issue, author, 'working', assignment_issue, proof_sha256, False)
        return self._request(task_id, person, None, None, 'working', assignment_issue, proof_sha256, False)

    def _request(self, task_id, person, number, author, action, assignment_issue, proof, coordinator):
        batch(task_id); require(person in PEOPLE and type(coordinator) is bool)
        internal = number is None
        require(internal and action == 'working' or integer(number))
        if not internal:
            actor(author); author = author.casefold()
        require(action == 'assign' or integer(assignment_issue))
        for attempt in range(self.max_attempts):
            sha, ledger = self._read()
            if not internal and str(number) in ledger['receipts']:
                item = ledger['receipts'][str(number)]
                self._binding(item, task_id, action, person, author, assignment_issue, proof)
                return self._result(item)
            current = ledger['assignments'].get(task_id)
            if internal and current and current['status'] == 'active' and current['person'] == person and current['assignment_issue'] == assignment_issue and current['work_proof_sha256'] == proof:
                return self._view(task_id, current)
            protected = current is not None and (current['origin'] == 'migration' or current['status'] != 'assigned')
            if protected and action == 'working':
                raise Unavailable('Working state is protected and cannot be replaced.')
            context = ({'definition_sha256': current['definition_sha256'], 'generation': current['catalogue_generation']}
                       if protected else self._catalogue(task_id))
            accepted = False
            if action == 'assign':
                if current is None:
                    if not context['assignment_enabled']:
                        raise Unavailable('This catalogue batch is not available for assignment.')
                    self._guard(task_id, action, None)
                    accepted = True
            elif action == 'release':
                if not protected and current is not None:
                    authorized = current['author'] == author or coordinator and author == self.owner
                    accepted = authorized and current['person'] == person and current['assignment_issue'] == assignment_issue
                    if accepted:
                        if current['definition_sha256'] != context['definition_sha256'] or current['catalogue_generation'] != context['generation']:
                            raise Unavailable('Reservation definition or catalogue generation changed.')
                        self._guard(task_id, action, current)
            else:
                if current is not None and not protected:
                    accepted = (current['person'] == person and current['assignment_issue'] == assignment_issue and
                                (internal or author in (current['author'], self.owner)))
                    if accepted:
                        if current['definition_sha256'] != context['definition_sha256'] or current['catalogue_generation'] != context['generation']:
                            raise Unavailable('Reservation definition or catalogue generation changed.')
                        self._guard(task_id, action, current, proof)
                if not accepted:
                    raise Unavailable('Work start no longer matches the reservation.')
            if not protected and self._catalogue(task_id) != context:
                raise Unavailable('Frozen catalogue changed during the operation.')
            now = self.clock(); stamp(now)
            updated = copy.deepcopy(ledger)
            if accepted:
                if action == 'assign':
                    updated['assignments'][task_id] = dict(batch_id=task_id, person=person, author=author,
                        assignment_issue=number, status='assigned', definition_sha256=context['definition_sha256'],
                        catalogue_generation=context['generation'], created_at=now, updated_at=now,
                        origin='github', work_proof_sha256=None, working_request_issue=None)
                elif action == 'release':
                    del updated['assignments'][task_id]
                else:
                    updated['assignments'][task_id].update(status='active', work_proof_sha256=proof, working_request_issue=number, updated_at=now)
            if not internal:
                item = dict(request_issue=number, batch_id=task_id, action=action, person=person, author=author,
                    assignment_issue=assignment_issue, proof_sha256=proof,
                    status=({'assign': 'confirmed', 'release': 'released', 'working': 'started'}[action] if accepted else 'rejected'),
                    recorded_at=now, definition_sha256=context['definition_sha256'], catalogue_generation=context['generation'], origin='github')
                updated['receipts'][str(number)] = item
            error = None
            try:
                self._put(sha, updated)
            except Exception as failure:
                error = failure
            # PUT success and uncertain ACK use the same observed-authority gate.
            _, observed = self._read()
            if not internal and str(number) in observed['receipts']:
                item = observed['receipts'][str(number)]
                self._binding(item, task_id, action, person, author, assignment_issue, proof)
                return self._result(item)
            active = observed['assignments'].get(task_id)
            if internal and active and active['status'] == 'active' and active['person'] == person and active['assignment_issue'] == assignment_issue and active['work_proof_sha256'] == proof:
                return self._view(task_id, active)
            if error is not None and error_status(error) == 409 and attempt + 1 < self.max_attempts:
                continue
            raise Unavailable('Assignment write is unconfirmed; reconcile the issue before another attempt.')
        raise Unavailable('Assignment CAS retry bound reached.')

    @staticmethod
    def _result(item):
        return dict(task_id=item['batch_id'], request_issue=item['request_issue'], action=item['action'],
                    person=item['person'], status=item['status'])

#!/usr/bin/env python3
"""Private shared-filesystem coordination; never executes collection instructions."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from counts import FULL_ISSUES, IDS, validate as validate_summary

PEOPLE = {name.lower(): name for name in
          ('Juan', 'Emily', 'Brian', 'Amir', 'Seann', 'Taha', 'Saswato', 'TH', 'Jion')}
PROFILE = {'max_interval_seconds': 900, 'min_years': 2, 'unexplained_gaps_allowed': 0}
IDENTITY = ('provider', 'instrument', 'venue', 'feed', 'currency', 'adjustment')
SCOPE_FIELDS = set(IDENTITY) | {'start', 'end', 'native_interval_seconds',
                              'native_resolution', 'history', 'coverage', 'meaning', 'budgets'}
KINDS = {'triage', 'metadata', 'preflight', 'collection'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'timestamp must have timezone')
    return parsed


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    require(not path.is_symlink(), 'symlink records unsupported')
    return json.loads(path.read_text())


def write(path, value):
    require(not path.parent.is_symlink() and not path.is_symlink(), 'symlink records unsupported')
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', value), 'invalid ID')
    return value


def validate_scope(scope):
    require(isinstance(scope, dict) and set(scope) == SCOPE_FIELDS, 'scope fields must match documented schema')
    for key in IDENTITY:
        require(scope[key] is None or isinstance(scope[key], str) and 0 < len(scope[key]) <= 200,
                'identity must be bounded text or null')
    start, end = date.fromisoformat(scope['start']), date.fromisoformat(scope['end'])
    require(start < end, 'scope window must be nonempty')
    require(type(scope['native_interval_seconds']) is int and 0 < scope['native_interval_seconds'] <= 900,
            'native interval must be at most 900 seconds')
    for key in ('native_resolution', 'history', 'coverage', 'meaning', 'budgets'):
        require(isinstance(scope[key], str) and 0 < len(scope[key]) <= 2000, 'scope requirements must be bounded text')
    return scope


def two_year_window(scope):
    start, end = date.fromisoformat(scope['start']), date.fromisoformat(scope['end'])
    try:
        anniversary = start.replace(year=start.year + 2)
    except ValueError:
        anniversary = start.replace(year=start.year + 2, day=28)
    require(end >= anniversary, 'two calendar years required')


def overlaps(left, right):
    # Unknown identity is a wildcard. Currency case is significant (GBP != GBp).
    same_resource = all(left[k] is None or right[k] is None or left[k] == right[k] for k in IDENTITY)
    return same_resource and left['start'] < right['end'] and right['start'] < left['end']


def validate_public_snapshot(data):
    """Fail closed before publishing the explicitly authorized aggregate schema."""
    require(isinstance(data, dict), 'invalid snapshot')
    version = data.get('schema_version')
    if type(version) is int and version == 3:
        return validate_self_service_snapshot(data)
    require(type(version) is int and version in (1, 2), 'invalid snapshot version')
    require(len(json.dumps(data).encode()) <= 16 * 1024 * 1024, 'public snapshot exceeds 16 MiB')
    batched = version == 2
    root_fields = {'schema_version', 'updated_at', 'profile', 'people', 'tasks'}
    require(set(data) == root_fields | ({'batch_limit'} if batched else set()), 'invalid snapshot fields')
    if batched:
        require(type(data['batch_limit']) is int and data['batch_limit'] == 500, 'invalid batch limit')
    require(data['profile'] == PROFILE and all(type(data['profile'][k]) is int for k in PROFILE), 'invalid profile')

    def timestamp(value):
        require(isinstance(value, str) and len(value) <= 40, 'invalid public timestamp')
        instant(value)

    def number(value, maximum=9007199254740991):
        require(type(value) is int and 0 <= value <= maximum, 'invalid public count')

    timestamp(data['updated_at'])
    require(isinstance(data['people'], list) and len(data['people']) == len(PEOPLE), 'invalid public roster')
    expected = {p: dict(id=p, name=name, queued=0, active=0, awaiting_verification=0, verified=0, load=0)
                for p, name in PEOPLE.items()}
    if batched:
        for person in expected.values():
            person.update(batched=0, remaining_series=0)
    require(isinstance(data['tasks'], list) and len(data['tasks']) <= (20000 if batched else 10000), 'invalid public task list')
    rows = {}
    children = {}
    for task in data['tasks']:
        fields = {'id', 'category', 'kind', 'status', 'assignee', 'effort', 'affected_series', 'issues', 'created_at', 'updated_at'}
        if batched:
            fields |= {'lead', 'parent_id', 'batch_number', 'batch_total'}
        require(isinstance(task, dict) and set(task) == fields, 'invalid public task fields')
        identifier(task['id'])
        require(task['id'] not in rows, 'duplicate task ID')
        rows[task['id']] = task
        require(task['category'] in IDS and task['kind'] in KINDS and task['assignee'] in PEOPLE, 'invalid public task category/kind/person')
        statuses = ('queued', 'active', 'blocked', 'awaiting_verification', 'verified') + (('batched',) if batched else ())
        require(task['status'] in statuses, 'invalid public task status')
        number(task['effort'], 100)
        require(task['effort'] > 0, 'effort must be positive')
        number(task['affected_series'])
        require(isinstance(task['issues'], list) and len(task['issues']) <= len(FULL_ISSUES) and all(isinstance(i, str) and i in FULL_ISSUES for i in task['issues']), 'invalid public reasons')
        require(len(set(task['issues'])) == len(task['issues']), 'duplicate public reasons')
        timestamp(task['created_at'])
        timestamp(task['updated_at'])
        if batched:
            require(task['lead'] in PEOPLE, 'invalid category lead')
            number(task['batch_number'], 20000)
            number(task['batch_total'], 20000)
            if task['parent_id'] is not None:
                identifier(task['parent_id'])
                require(task['kind'] == 'triage' and task['status'] != 'batched', 'invalid batch kind/status')
                require(0 < task['affected_series'] <= 500 and 0 < task['batch_number'] <= task['batch_total'], 'invalid batch range/count')
                require(task['effort'] == min(5, (task['affected_series'] + 99) // 100), 'invalid batch effort')
                children.setdefault(task['parent_id'], []).append(task)
            else:
                require(task['batch_number'] == 0, 'unexpected batch number')
                require((task['status'] == 'batched') == (task['batch_total'] > 0), 'invalid parent batch status')
        person = expected[task['assignee']]
        person['active' if task['status'] == 'blocked' else task['status']] += 1
        if task['status'] not in ('verified', 'batched'):
            person['load'] += task['effort']
            if batched and task['kind'] == 'triage':
                person['remaining_series'] += task['affected_series']
    if batched:
        for task in rows.values():
            if task['status'] == 'batched':
                require(task['id'] in children and task['kind'] == 'triage' and task['lead'] == task['assignee'], 'missing batches or invalid lead')
        for parent_id, batches in children.items():
            parent = rows.get(parent_id)
            require(parent is not None and parent['status'] == 'batched' and parent['parent_id'] is None, 'invalid batch parent')
            total = parent['batch_total']
            require(len(batches) == total and {t['batch_number'] for t in batches} == set(range(1, total + 1)), 'inconsistent batch numbering')
            require(all(t['batch_total'] == total and t['category'] == parent['category'] and t['lead'] == parent['assignee'] for t in batches), 'inconsistent batch ownership/category')
    seen_people = set()
    for person in data['people']:
        fields = {'id', 'name', 'queued', 'active', 'awaiting_verification', 'verified', 'load'}
        if batched:
            fields |= {'batched', 'remaining_series'}
        require(isinstance(person, dict) and set(person) == fields, 'invalid public person fields')
        require(isinstance(person['id'], str) and person['id'] in PEOPLE and person['id'] not in seen_people, 'invalid public person')
        seen_people.add(person['id'])
        for key in fields - {'id', 'name'}:
            number(person[key])
        require(person == expected[person['id']], 'public person totals/name mismatch')
    return data


def validate_self_service_snapshot(data):
    """Schema 3 publishes actual assignments, never historical allocation hints."""
    require(set(data) == {'schema_version', 'updated_at', 'profile', 'people', 'tasks', 'batch_limit'},
            'invalid self-service snapshot fields')
    require(len(json.dumps(data).encode()) <= 16 * 1024 * 1024, 'public snapshot exceeds 16 MiB')
    require(type(data['batch_limit']) is int and data['batch_limit'] == 500, 'invalid batch limit')
    require(data['profile'] == PROFILE and all(type(data['profile'][k]) is int for k in PROFILE), 'invalid profile')

    def timestamp(value):
        require(isinstance(value, str) and len(value) <= 40, 'invalid public timestamp')
        instant(value)

    def number(value, maximum=9007199254740991):
        require(type(value) is int and 0 <= value <= maximum, 'invalid public count')

    timestamp(data['updated_at'])
    require(isinstance(data['tasks'], list) and len(data['tasks']) <= 20000, 'invalid public task list')
    expected = {p: dict(id=p, name=name, assigned=0, active=0, awaiting_verification=0,
                        verified=0, remaining_series=0) for p, name in PEOPLE.items()}
    fields = {'id', 'category', 'kind', 'status', 'assignee', 'affected_series', 'issues',
              'created_at', 'updated_at', 'parent_id', 'batch_number', 'batch_total', 'assignment_issue'}
    rows, children = {}, {}
    for task in data['tasks']:
        require(isinstance(task, dict) and set(task) == fields, 'invalid public task fields')
        identifier(task['id'])
        require(task['id'] not in rows, 'duplicate task ID')
        rows[task['id']] = task
        require(task['category'] in IDS and task['kind'] in KINDS, 'invalid public task category/kind')
        status, person = task['status'], task['assignee']
        require(status in ('available', 'assigned', 'active', 'blocked', 'awaiting_verification', 'verified', 'batched'),
                'invalid public task status')
        require((person is None and status in ('available', 'batched')) or
                (isinstance(person, str) and person in PEOPLE and status not in ('available', 'batched')),
                'invalid public assignment')
        issue = task['assignment_issue']
        require(issue is None or type(issue) is int and 0 < issue <= 9007199254740991,
                'invalid assignment issue')
        require(status not in ('available', 'batched') or issue is None, 'unassigned task has assignment issue')
        number(task['affected_series'])
        require(isinstance(task['issues'], list) and len(task['issues']) <= len(FULL_ISSUES) and
                all(isinstance(i, str) and i in FULL_ISSUES for i in task['issues']) and
                len(set(task['issues'])) == len(task['issues']), 'invalid public reasons')
        timestamp(task['created_at'])
        timestamp(task['updated_at'])
        number(task['batch_number'], 20000)
        number(task['batch_total'], 20000)
        if task['parent_id'] is not None:
            identifier(task['parent_id'])
            require(task['kind'] == 'triage' and status != 'batched' and
                    0 < task['affected_series'] <= 500 and
                    0 < task['batch_number'] <= task['batch_total'], 'invalid batch range/count')
            children.setdefault(task['parent_id'], []).append(task)
        else:
            require(task['batch_number'] == 0 and ((status == 'batched') == (task['batch_total'] > 0)),
                    'invalid parent batch status')
        if person is not None:
            expected[person]['active' if status == 'blocked' else status] += 1
            if status != 'verified' and task['kind'] == 'triage':
                expected[person]['remaining_series'] += task['affected_series']
    for task in rows.values():
        if task['status'] == 'batched':
            require(task['id'] in children and task['kind'] == 'triage', 'missing batches')
    for parent_id, batches in children.items():
        parent = rows.get(parent_id)
        require(parent is not None and parent['status'] == 'batched' and parent['parent_id'] is None,
                'invalid batch parent')
        total = parent['batch_total']
        require(len(batches) == total and {t['batch_number'] for t in batches} == set(range(1, total + 1)) and
                all(t['batch_total'] == total and t['category'] == parent['category'] for t in batches),
                'inconsistent batch numbering/category')
    require(isinstance(data['people'], list) and len(data['people']) == len(PEOPLE), 'invalid public roster')
    seen = set()
    for person in data['people']:
        require(isinstance(person, dict) and set(person) == set(next(iter(expected.values()))), 'invalid public person fields')
        person_id = person['id']
        require(isinstance(person_id, str) and person_id in PEOPLE and person_id not in seen, 'invalid public person')
        seen.add(person_id)
        for key in set(person) - {'id', 'name'}:
            number(person[key])
        require(person == expected[person_id], 'public person totals/name mismatch')
    return data


class Hub:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self._self_service = None
        self._mode_loaded = False

    def self_service(self):
        # Mode is immutable for a command; avoid a protected JSON read per leaf.
        if not self._mode_loaded:
            require(not (self.root / '.self-service-migration-lock').exists(),
                    'incomplete self-service migration; reconcile manually')
            path = self.root / 'self-service.json'
            if path.exists():
                self.protected(path)
                config = read(path)
                require(set(config) == {'schema_version', 'status', 'enabled_at', 'sentinel_ids'} and
                        config['schema_version'] == 1 and config['status'] == 'enabled',
                        'incomplete self-service migration; reconcile manually')
                require(isinstance(config['sentinel_ids'], list) and
                        len(set(config['sentinel_ids'])) == len(config['sentinel_ids']), 'invalid sentinel IDs')
                for task_id in config['sentinel_ids']:
                    identifier(task_id)
                self.protected(self.root / 'assignments')
                for name in ('work-claims', 'task-locks'):
                    self.shared_directory(name)
                self._self_service = frozenset(config['sentinel_ids'])
            self._mode_loaded = True
        return self._self_service is not None

    def enable_self_service(self):
        """One deliberate migration; interruptions retain a lock and fail closed."""
        with self.coordinator():
            config_path = self.root / 'self-service.json'
            require(not config_path.exists(), 'self-service migration already recorded; do not repeat')
            lock = self.root / '.self-service-migration-lock'
            lock.mkdir()
            self._mode_loaded = False
            config = dict(schema_version=1, status='migrating', enabled_at=now(), sentinel_ids=[])
            write(config_path, config)
            journal_path = lock / 'sentinels.jsonl'
            journal_path.touch(mode=0o644, exist_ok=False)
            os.chmod(journal_path, 0o644)
            plans = self.batch_plans()
            for name in ('assignments', 'work-claims', 'task-locks'):
                directory = self.root / name
                require(not directory.is_symlink(), 'symlink directory unsupported')
                directory.mkdir()
                os.chmod(directory, 0o755 if name == 'assignments' else 0o1777)
            for task in self.tasks():
                if task['id'] in plans:
                    continue  # Original parent reservation remains legacy-compatible.
                path = self.root / 'claims' / task['id']
                try:
                    path.mkdir(mode=0o755)
                except FileExistsError:
                    # A legacy worker may win this exact mkdir race; preserve its claim.
                    self.claim_record(task)
                    continue
                os.chmod(path, 0o755)
                write(path / 'owner.json', dict(uid=os.getuid(), person=task['assignee'],
                                                task_sha256=digest(task), claimed_at=now()))
                with journal_path.open('a') as journal:
                    journal.write(json.dumps(dict(task_id=task['id'], task_sha256=digest(task))) + '\n')
                    journal.flush()
                    os.fsync(journal.fileno())
                config['sentinel_ids'].append(task['id'])
            config['status'] = 'enabled'
            write(config_path, config)
            journal_path.unlink()
            lock.rmdir()
            self._mode_loaded = False
            self.self_service()
            return dict(status='enabled', blocked_legacy_claims=len(config['sentinel_ids']))

    def shared_directory(self, name):
        directory = self.root / name
        require(not directory.is_symlink(), 'symlink shared directory unsupported')
        info = directory.stat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o1777 and
                info.st_uid == self.root.stat().st_uid, 'invalid shared directory')
        return directory

    @contextmanager
    def task_lock(self, task_id):
        identifier(task_id)
        directory = self.shared_directory('task-locks')
        lock = directory / task_id
        lock.mkdir(mode=0o755)  # Never steal, retry or remove another operation's lock.
        os.chmod(lock, 0o755)
        try:
            yield
        finally:
            lock.rmdir()

    def reservation(self, task):
        path = self.root / 'assignments' / (task['id'] + '.json')
        if not path.exists():
            require(not path.is_symlink(), 'symlink assignment unsupported')
            return None
        self.protected(path)
        record = read(path)
        require(set(record) in ({'task_sha256', 'current', 'history'},
                                {'task_sha256', 'current', 'history', 'requests'}) and
                record['task_sha256'] == digest(task) and isinstance(record['history'], list),
                'assignment task hash/record mismatch; reconcile manually')
        requests = record.get('requests', {})
        require(isinstance(requests, dict), 'invalid request receipts')
        for issue, receipt in requests.items():
            require(isinstance(issue, str) and issue.isascii() and issue.isdecimal() and
                    str(int(issue)) == issue, 'invalid request receipt issue')
            self.validate_request_receipt(receipt, task['id'], int(issue))
        current = record['current']
        if current is not None:
            require(set(current) == {'person', 'issue', 'github_author', 'assigned_at'} and
                    current['person'] in PEOPLE and type(current['issue']) is int and current['issue'] > 0,
                    'invalid assignment record')
            self.github_author(current['github_author'])
            require(instant(current['assigned_at']) <= datetime.now(timezone.utc), 'invalid assignment timestamp')
        return record

    @staticmethod
    def validate_request_receipt(receipt, task_id, issue):
        require(type(issue) is int and 0 < issue <= 9007199254740991, 'invalid request issue')
        require(isinstance(receipt, dict) and set(receipt) ==
                {'task_id', 'request_issue', 'action', 'person', 'status'} and
                receipt['task_id'] == task_id and type(receipt['request_issue']) is int and
                receipt['request_issue'] == issue and receipt['person'] in PEOPLE and
                (receipt['action'], receipt['status']) in (('assign', 'confirmed'), ('release', 'released')),
                'invalid request receipt')
        return receipt

    def request_receipt(self, record, task_id, issue):
        require(type(issue) is int and 0 < issue <= 9007199254740991, 'invalid request issue')
        if record is None:
            return None
        receipt = record.get('requests', {}).get(str(issue))
        if receipt is not None:
            return receipt
        # Existing reservations/history are already durable evidence of the original
        # assign request. Do not resurrect one released before receipts were added.
        entries = record['history'] + ([record['current']] if record['current'] else [])
        for entry in entries:
            if entry.get('issue') == issue:
                return self.validate_request_receipt(
                    dict(task_id=task_id, request_issue=issue, action='assign',
                         person=entry['person'], status='confirmed'), task_id, issue)
        return None

    def request_status(self, task_id, issue):
        """Return the original safe request outcome, independently of current work."""
        require(self.self_service(), 'self-service mode required')
        task = self.task(task_id)
        return self.request_receipt(self.reservation(task), task_id, issue)

    @staticmethod
    def record_request(record, task_id, issue, action, person):
        record.setdefault('requests', {})[str(issue)] = dict(
            task_id=task_id, request_issue=issue, action=action, person=person,
            status='confirmed' if action == 'assign' else 'released')

    @staticmethod
    def github_author(value):
        require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?', value),
                'invalid GitHub author')
        return value

    def work_claim_record(self, task):
        """Resolve real worker claims; legacy sentinels are never worker identities."""
        if not self.self_service():
            path = self.root / 'claims' / task['id']
            return self.claim_record(task) if path.exists() else None
        legacy = self.root / 'claims' / task['id']
        if task['id'] in self._self_service:
            _, sentinel = self.claim_record(task)
            require(sentinel['uid'] == self.root.stat().st_uid, 'sentinel ownership changed')
        elif legacy.exists():
            require(not (self.root / 'work-claims' / task['id']).exists(), 'duplicate worker claims; reconcile manually')
            return self.claim_record(task)
        path = self.root / 'work-claims' / task['id']
        require(not path.is_symlink(), 'symlink claim unsupported')
        if not path.exists():
            return None
        info = path.stat()
        require(info.st_mode & 0o022 == 0, 'claim must be owner-writable only')
        owner = read(path / 'owner.json')
        require(set(owner) == {'uid', 'person', 'task_sha256', 'claimed_at'} and
                type(owner['uid']) is int and owner['uid'] == info.st_uid and owner['person'] in PEOPLE,
                'claim ownership mismatch')
        require(owner['task_sha256'] == digest(task), 'task changed after claim; manual reconciliation required')
        require(instant(owner['claimed_at']) <= datetime.now(timezone.utc), 'invalid claim timestamp')
        return path, owner

    def effective_assignee(self, task, plans=None):
        if not self.self_service():
            return task['assignee']
        plans = self.batch_plans() if plans is None else plans
        if task['id'] in plans:
            return None
        claim = self.work_claim_record(task)
        if claim:
            return claim[1]['person']
        record = self.reservation(task)
        return record['current']['person'] if record and record['current'] else None

    def assign(self, task_id=None, person=None, issue=None, github_author=None):
        if task_id is None:
            require(not self.self_service(), 'automatic allocation disabled in self-service mode')
            loads = self.loads()
            return min(PEOPLE, key=lambda p: (loads[p], list(PEOPLE).index(p)))
        require(self.self_service(), 'self-service mode required')
        require(person in PEOPLE and type(issue) is int and 0 < issue <= 9007199254740991, 'invalid person/issue')
        self.github_author(github_author)
        with self.coordinator(), self.task_lock(task_id):
            task = self.task(task_id)
            status, _ = self.state(task)
            record = self.reservation(task)
            current = record['current'] if record else None
            receipt = self.request_receipt(record, task_id, issue)
            if receipt is not None:
                require(receipt['action'] == 'assign' and receipt['person'] == person,
                        'request issue already used for a different action or participant')
                original_issue = current['issue'] if current and current['person'] == person else issue
                return dict(status=status, task_id=task_id, person=person, issue=original_issue)
            if current:
                require(current['person'] == person, 'task reserved by another participant')
                self.record_request(record, task_id, issue, 'assign', person)
                write(self.root / 'assignments' / (task_id + '.json'), record)
                return dict(status=status, task_id=task_id, person=person, issue=current['issue'])
            require(status == 'available', 'task already claimed or unavailable')
            current = dict(person=person, issue=issue, github_author=github_author, assigned_at=now())
            record = record or dict(task_sha256=digest(task), current=None, history=[])
            record['current'] = current
            self.record_request(record, task_id, issue, 'assign', person)
            write(self.root / 'assignments' / (task_id + '.json'), record)
            return dict(status='assigned', task_id=task_id, person=person, issue=issue)

    def release_assignment(self, task_id, person, github_author, coordinator=False,
                           request_issue=None, assignment_issue=None):
        require(self.self_service(), 'self-service mode required')
        self.github_author(github_author)
        if request_issue is not None:
            require(type(request_issue) is int and 0 < request_issue <= 9007199254740991 and
                    type(assignment_issue) is int and 0 < assignment_issue <= 9007199254740991,
                    'GitHub release requires request and expected assignment issues')
        else:
            require(assignment_issue is None, 'expected assignment requires a request issue')
        with self.coordinator(), self.task_lock(task_id):
            task = self.task(task_id)
            record = self.reservation(task)
            if request_issue is not None:
                receipt = self.request_receipt(record, task_id, request_issue)
                if receipt is not None:
                    require(receipt['action'] == 'release' and receipt['person'] == person,
                            'request issue already used for a different action or participant')
                    return dict(status='available', task_id=task_id, person=person, issue=assignment_issue)
            require(self.work_claim_record(task) is None, 'cannot release an actual worker claim')
            require(record is not None and record['current'] is not None, 'no current assignment')
            current = record['current']
            require(current['person'] == person, 'assignment person mismatch')
            if request_issue is not None:
                require(current['issue'] == assignment_issue, 'reservation changed since release request')
            require(coordinator or current['github_author'].lower() == github_author.lower(),
                    'only origin author or coordinator may release')
            released = dict(current, released_at=now(), released_by=github_author,
                            coordinator=bool(coordinator))
            if request_issue is not None:
                released['release_request_issue'] = request_issue
                self.record_request(record, task_id, request_issue, 'release', person)
            record['history'].append(released)
            record['current'] = None
            write(self.root / 'assignments' / (task_id + '.json'), record)
            return dict(status='available', task_id=task_id, person=person, issue=current['issue'])

    def assignment_status(self, task_id):
        require(self.self_service(), 'self-service mode required')
        task = self.task(task_id)
        plans = self.batch_plans()
        status, _ = self.state(task, plans)
        record = self.reservation(task) if status != 'batched' else None
        return dict(task_id=task_id, status=status, assignee=self.effective_assignee(task, plans),
                    assignment_issue=record['current']['issue'] if record and record['current'] else None)

    def show(self, task_id, plans=None):
        return self.task_view(self.task(task_id), plans)

    def task_view(self, task, plans=None):
        status, updated = self.state(task, plans)
        row = dict(task, status=status, updated_at=updated, task_sha256=digest(task))
        if self.self_service():
            row.pop('effort', None)
            row.pop('lead', None)
            row['assignee'] = self.effective_assignee(task, plans)
            record = self.reservation(task) if status != 'batched' else None
            row['assignment_issue'] = record['current']['issue'] if record and record['current'] else None
        return row

    def init(self):
        require(not self.root.is_symlink(), 'symlink hub unsupported')
        try:
            self.root.mkdir(mode=0o755, parents=True)
        except FileExistsError:
            pass
        else:
            os.chmod(self.root, 0o755)
        require(self.root.stat().st_uid == os.getuid(), 'only hub owner may initialize')
        require(self.root.stat().st_mode & 0o022 == 0, 'hub must not be group/world writable')
        for name in ('tasks', 'verified', 'claims', 'proposals'):
            path = self.root / name
            require(not path.is_symlink(), 'symlink directory unsupported')
            path.mkdir(exist_ok=True)
            os.chmod(path, 0o1777 if name in ('claims', 'proposals') else 0o755)
        return {'initialized': True}

    def protected(self, path):
        owner = self.root.stat().st_uid
        for target in (self.root, path.parent, path):
            require(not target.is_symlink(), 'symlink protected path unsupported')
            info = target.stat()
            require(info.st_uid == owner and info.st_mode & 0o022 == 0, 'unprotected coordinator definition')

    @contextmanager
    def coordinator(self):
        self.protected(self.root / 'tasks')
        require(self.root.stat().st_uid == os.getuid(), 'coordinator owner required')
        lock = self.root / '.coordinator-lock'
        lock.mkdir()  # Persistent on interruption; never automatically stolen.
        try:
            yield
        finally:
            lock.rmdir()

    def batch_plans(self):
        directory = self.root / 'batch-plans'
        if not directory.exists():
            return {}
        self.protected(directory)
        require(not list(directory.glob('.*.incoming')), 'interrupted batch staging requires manual reconciliation')
        plans = {}
        for path in sorted(directory.iterdir()):
            require(path.is_dir() and not path.name.startswith('.'), 'unexpected batch plan; reconcile manually')
            self.protected(path / 'plan.json')
            plan = read(path / 'plan.json')
            fields = {'manifest_path', 'manifest_sha256', 'assignment', 'batch_size', 'parent_id',
                      'parent_sha256', 'child_prefix', 'batch_total', 'activated_at'}
            require(isinstance(plan, dict) and set(plan) == fields, 'invalid batch plan; reconcile manually')
            require(plan['assignment'] in ('lead', 'balanced') and type(plan['batch_size']) is int and
                    1 <= plan['batch_size'] <= 500, 'invalid batch policy; reconcile manually')
            require(type(plan['batch_total']) is int and 1 <= plan['batch_total'] <= 20000,
                    'invalid batch total; reconcile manually')
            require(isinstance(plan['manifest_path'], str) and Path(plan['manifest_path']).is_absolute() and
                    isinstance(plan['manifest_sha256'], str) and re.fullmatch('[0-9a-f]{64}', plan['manifest_sha256']),
                    'invalid manifest pin; reconcile manually')
            require(instant(plan['activated_at']) <= datetime.now(timezone.utc), 'invalid batch activation time')
            parent = self._read_task(self.root / 'tasks' / (identifier(path.name) + '.json'))
            require(plan['parent_id'] == parent['id'] and plan['parent_sha256'] == digest(parent), 'batch parent changed; reconcile manually')
            require(plan['child_prefix'] == 'batch-' + digest(parent)[:24] + '-', 'invalid child prefix; reconcile manually')
            self.claim_record(parent)
            plans[parent['id']] = plan
        return plans

    def _read_task(self, path):
        self.protected(path)
        task = read(path)
        require(task['id'] == path.stem, 'task ID mismatch')
        return task

    def task(self, task_id):
        identifier(task_id)
        path = self.root / 'tasks' / (task_id + '.json')
        if path.exists():
            return self._read_task(path)
        for parent_id, plan in self.batch_plans().items():
            if task_id.startswith(plan['child_prefix']):
                return self._read_task(self.root / 'batch-plans' / parent_id / 'tasks' / (task_id + '.json'))
        raise ValueError('unknown task ID')

    def tasks(self):
        plans = self.batch_plans()
        paths = sorted((self.root / 'tasks').glob('*.json'))
        for parent_id, plan in plans.items():
            children = sorted((self.root / 'batch-plans' / parent_id / 'tasks').glob('*.json'))
            require(len(children) == plan['batch_total'], 'incomplete batch plan; reconcile manually')
            paths.extend(children)
        return [self._read_task(path) for path in paths]

    def claim_record(self, task):
        path = self.root / 'claims' / task['id']
        require(not path.is_symlink(), 'symlink claim unsupported')
        info = path.stat()
        require(info.st_mode & 0o022 == 0, 'claim must be owner-writable only')
        owner = read(path / 'owner.json')
        require(set(owner) == {'uid', 'person', 'task_sha256', 'claimed_at'}, 'invalid claim fields')
        require(owner['uid'] == info.st_uid and owner['person'] == task['assignee'], 'claim ownership mismatch')
        require(owner['task_sha256'] == digest(task), 'task changed after claim; manual reconciliation required')
        require(instant(owner['claimed_at']) <= datetime.now(timezone.utc), 'invalid claim timestamp')
        return path, owner

    def state(self, task, plans=None):
        self.self_service()  # An incomplete migration fails closed even for parents.
        if task['kind'] == 'triage' and 'batch_spec' not in task:
            plans = self.batch_plans() if plans is None else plans
            if task['id'] in plans:
                return 'batched', plans[task['id']]['activated_at']
        receipt = self.root / 'verified' / (task['id'] + '.json')
        if receipt.exists():
            self.protected(receipt)
            require(read(receipt)['task_sha256'] == digest(task), 'verification task hash mismatch')
            return 'verified', read(receipt)['verified_at']
        claim = self.work_claim_record(task)
        if claim is None:
            if self.self_service():
                reservation = self.reservation(task)
                if reservation and reservation['current']:
                    return 'assigned', reservation['current']['assigned_at']
                return 'available', task['created_at']
            return 'queued', task['created_at']
        path, owner = claim
        reports = [read(p) for p in path.glob('report-*.json')]
        if not reports:
            return 'active', owner['claimed_at']
        for report in reports:
            require(isinstance(report, dict) and set(report) == {'person', 'uid', 'task_sha256', 'at', 'status', 'note'}, 'invalid report fields')
            require(report['uid'] == owner['uid'] and report['person'] == owner['person'], 'report owner mismatch')
            require(report['task_sha256'] == digest(task), 'report task hash mismatch')
            require(report['status'] in ('active', 'blocked', 'awaiting_verification'), 'worker cannot verify a task')
            require(isinstance(report['note'], str) and 0 < len(report['note'].strip()) <= 4000, 'invalid report note')
            require(instant(owner['claimed_at']) <= instant(report['at']) <= datetime.now(timezone.utc), 'invalid report timestamp')
        latest = max(reports, key=lambda r: instant(r['at']))
        return latest['status'], latest['at']

    def loads(self):
        require(not self.self_service(), 'historical allocation loads disabled in self-service mode')
        loads = dict.fromkeys(PEOPLE, 0)
        for task in self.tasks():
            if self.state(task)[0] not in ('verified', 'batched'):
                loads[task['assignee']] += task['effort']
        return loads

    def seed(self, summary):
        validate_summary(summary)
        require(summary['schema'] == 4, 'schema 4 required')
        created = []
        with self.coordinator():
            existing_triage = [task for task in self.tasks() if task['kind'] == 'triage']
            unfinished_categories = {
                task['category'] for task in existing_triage if self.state(task)[0] != 'verified'
            }
            # Large categories are placed first for deterministic least-load packing.
            for category in sorted(summary['types'], key=lambda c: (-c['excluded_series'], c['id'])):
                if category['id'] in unfinished_categories:
                    continue
                if any(task['category'] == category['id'] and
                       instant(task['audit_utc']) >= instant(summary['audit_utc'])
                       for task in existing_triage):
                    continue
                key = digest({'audit': summary['audit_utc'], 'category': category['id']})
                task_id = 'triage-' + key[:24]
                if (self.root / 'tasks' / (task_id + '.json')).exists():
                    continue
                task = {'id': task_id, 'category': category['id'], 'kind': 'triage',
                        'assignee': None if self.self_service() else self.assign(), 'effort': 1, 'affected_series': category['excluded_series'],
                        'issues': [i['id'] for i in category['issues'] if i['count']],
                        'issue_totals': category['issues'], 'source_failures': category['source_failures'],
                        'audit_utc': summary['audit_utc'], 'assessment_utc': summary['assessment_utc'],
                        'created_at': now(), 'scope': None}
                write(self.root / 'tasks' / (task_id + '.json'), task)
                created.append(task_id)
        return created

    def claim(self, task_id, person):
        require(person in PEOPLE, 'unknown person')
        if self.self_service():
            with self.task_lock(task_id):
                task = self.task(task_id)
                require(self.state(task)[0] in ('available', 'assigned'), 'task already claimed or unavailable')
                assignee = self.effective_assignee(task)
                require(assignee is None or person == assignee, 'task assigned to another participant')
                path = self.root / 'work-claims' / task_id
                path.mkdir(mode=0o755)
                os.chmod(path, 0o755)
                owner = dict(person=person, uid=os.getuid(), task_sha256=digest(task), claimed_at=now())
                write(path / 'owner.json', owner)
                require(digest(self.task(task_id)) == digest(task), 'task changed during claim')
                return owner
        task = self.task(task_id)
        require(person == task['assignee'], 'task assigned to another participant')
        require(self.state(task)[0] == 'queued', 'task already claimed or verified')
        path = self.root / 'claims' / task_id
        path.mkdir(mode=0o755)  # Exclusive, persistent claim; no expiry or retries.
        os.chmod(path, 0o755)  # Shared traversal must not depend on claimant umask.
        owner = {'person': person, 'uid': os.getuid(), 'task_sha256': digest(task), 'claimed_at': now()}
        write(path / 'owner.json', owner)
        require(digest(self.task(task_id)) == digest(task), 'task changed during claim')
        return owner

    def report(self, task_id, person, status, note):
        require(status in ('in_progress', 'blocked', 'completed'), 'invalid report status')
        require(isinstance(note, str) and 0 < len(note.strip()) <= 4000, 'note must contain 1–4000 characters')
        task = self.task(task_id)
        claim = self.work_claim_record(task)
        require(claim is not None, 'actual worker claim required')
        path, owner = claim
        require(owner['uid'] == os.getuid() and owner['person'] == person, 'only actual claim owner may report')
        lock = path / '.report-lock'
        lock.mkdir()
        try:
            require(self.state(task)[0] not in ('verified', 'awaiting_verification', 'batched'), 'task completion is final pending coordinator review')
            record = {'person': person, 'uid': os.getuid(), 'task_sha256': digest(task), 'at': now(),
                      'status': {'in_progress': 'active', 'blocked': 'blocked', 'completed': 'awaiting_verification'}[status],
                      'note': note}
            write(path / ('report-' + uuid.uuid4().hex + '.json'), record)
            require(digest(self.task(task_id)) == digest(task), 'task changed during report')
            return record
        finally:
            lock.rmdir()

    def propose(self, proposal, person):
        require(person in PEOPLE, 'unknown person')
        self.validate_admission(proposal)
        require(len(json.dumps(proposal)) <= 30000, 'proposal too large')
        proposal_id = uuid.uuid4().hex
        path = self.root / 'proposals' / proposal_id
        path.mkdir(mode=0o755)
        os.chmod(path, 0o755)
        write(path / 'proposal.json', {'proposal': proposal, 'person': person, 'uid': os.getuid(), 'at': now()})
        return proposal_id

    def admit(self, proposal_id):
        with self.coordinator():
            path = self.root / 'proposals' / identifier(proposal_id)
            require(not path.is_symlink(), 'symlink proposal unsupported')
            record = read(path / 'proposal.json')
            require(path.stat().st_uid == record['uid'], 'proposal uid mismatch')
            proposal = record['proposal']
            # Revalidate untrusted proposal without creating another proposal record.
            self.validate_admission(proposal)
            task_id = 'work-' + digest(proposal)[:24]
            if (self.root / 'tasks' / (task_id + '.json')).exists():
                return {'admitted': False, 'conflicts_with': task_id}
            for task in self.tasks():
                if task['kind'] != 'collection' and self.state(task)[0] == 'verified':
                    continue  # Reviewed plans may be followed by scoped implementation.
                if task['scope'] is not None and overlaps(task['scope'], proposal['scope']):
                    return {'admitted': False, 'conflicts_with': task['id']}
            task = dict(proposal, id=task_id, assignee=None if self.self_service() else self.assign(), created_at=now())
            write(self.root / 'tasks' / (task_id + '.json'), task)
            return {'admitted': True, 'task_id': task_id}

    def validate_admission(self, proposal):
        allowed = {'category', 'kind', 'effort', 'affected_series', 'issues', 'scope', 'preflight'}
        require(isinstance(proposal, dict) and set(proposal) <= allowed and allowed - ({'preflight', 'effort'} if self.self_service() else {'preflight'}) <= set(proposal), 'unexpected proposal fields')
        require(proposal['category'] in IDS and proposal['kind'] in KINDS - {'triage'}, 'invalid proposal category/kind')
        if 'effort' in proposal:
            require(type(proposal['effort']) is int and 1 <= proposal['effort'] <= 100, 'invalid effort')
        require(type(proposal['affected_series']) is int and proposal['affected_series'] >= 0, 'invalid count')
        require(isinstance(proposal['issues'], list) and all(i in FULL_ISSUES for i in proposal['issues']), 'invalid issues')
        scope = validate_scope(proposal['scope'])
        if proposal['kind'] == 'collection':
            two_year_window(scope)
            require(all(scope[k] is not None for k in IDENTITY), 'collection requires complete source identity')
            receipt = proposal.get('preflight', {})
            require(receipt.get('verified') is True and receipt.get('kind') == 'preflight', 'verified preflight required')
            require(receipt.get('scope_sha256') == digest(scope), 'preflight scope mismatch')
            require(receipt.get('evidence') and isinstance(receipt['evidence'], str), 'preflight evidence required')
            require(instant(receipt['verified_at']) <= datetime.now(timezone.utc), 'preflight cannot be future-dated')
            require(all(receipt.get('checks', {}).get(k) is True for k in
                        ('native_resolution', 'history', 'coverage', 'meaning', 'budgets')), 'preflight checks incomplete')

    def verify(self, task_id, receipt):
        with self.coordinator():
            task = self.task(task_id)
            status, completed_at = self.state(task)
            require(status == 'awaiting_verification', 'worker completion required before verification')
            require(receipt.get('task_sha256') == digest(task), 'receipt task mismatch')
            require(receipt.get('verified') is True and isinstance(receipt.get('evidence'), str) and receipt['evidence'], 'reviewed external evidence required')
            require(instant(receipt['verified_at']) >= instant(completed_at), 'verification must follow completion')
            require(instant(receipt['verified_at']) <= datetime.now(timezone.utc), 'verification cannot be future-dated')
            if task['kind'] == 'collection':
                scope = task['scope']
                require(receipt.get('kind') == 'audit' and receipt.get('scope_sha256') == digest(scope), 'exact audit scope required')
                require(receipt.get('source_identity') == {k: scope[k] for k in IDENTITY}, 'audit source identity mismatch')
                require(receipt.get('window') == {k: scope[k] for k in ('start', 'end')}, 'audit window mismatch')
                two_year_window(scope)
                interval = receipt.get('native_interval_seconds')
                require(type(interval) is int and 0 < interval <= 900 and interval == scope['native_interval_seconds'], 'audit native interval mismatch')
                require(type(receipt.get('unexplained_gaps')) is int and receipt['unexplained_gaps'] == 0 and receipt.get('eligible') is True, 'audit not eligible')
                require(instant(receipt['audited_at']) >= instant(completed_at), 'fresh audit after completion required')
                require(instant(receipt['audited_at']) <= instant(receipt['verified_at']), 'audit must precede verification')
            else:
                require(receipt.get('kind') == 'plan', 'noncollection verification certifies a plan only')
            write(self.root / 'verified' / (task_id + '.json'), receipt)
            return {'status': 'verified', 'certifies_data': task['kind'] == 'collection'}

    @staticmethod
    def catalogue_page(manifest, page):
        relative = page['path']
        require(isinstance(relative, str) and relative and '\\' not in relative,
                'catalogue page path must be relative')
        parts = relative.split('/')
        require(not Path(relative).is_absolute() and all(part not in ('', '.', '..') for part in parts),
                'catalogue page path must stay inside its package')
        target = Path(manifest).parent.resolve()
        for index, part in enumerate(parts):
            target = target / part
            info = target.lstat()
            require(not stat.S_ISLNK(info.st_mode), 'symlink catalogue path unsupported')
            if index < len(parts) - 1:
                require(stat.S_ISDIR(info.st_mode), 'catalogue ancestor must be a directory')
            else:
                require(stat.S_ISREG(info.st_mode), 'catalogue page must be a regular file')
                require(info.st_size == page['bytes'] and page['bytes'] <= 32 * 1024 * 1024,
                        'page size mismatch or too large')
        return target

    @staticmethod
    def manifest(path):
        path = Path(path).absolute()
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 16 * 1024 * 1024, 'invalid manifest file')
        raw = path.read_bytes()
        data = json.loads(raw)
        require(data.get('schema') == 'kuina-inspection-v1' and isinstance(data.get('datasets'), list), 'invalid catalogue manifest')
        requirements = data.get('requirements')
        require(requirements == {'maxNativeSeconds': 900, 'minHistoryYears': 2} and
                all(type(value) is int for value in requirements.values()), 'catalogue requirements must match 900 seconds/two years')
        for key in ('windowStart', 'windowEnd'):
            value = data.get(key)
            require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value,
                    'catalogue window must declare ISO dates')
        two_year_window({'start': data['windowStart'], 'end': data['windowEnd']})
        seen_ids, seen_pages = set(), set()
        for dataset in data['datasets']:
            require(isinstance(dataset, dict) and isinstance(dataset.get('id'), str) and dataset['id'] not in seen_ids, 'invalid dataset ID')
            seen_ids.add(dataset['id'])
            require(dataset.get('type') in IDS and isinstance(dataset.get('pages'), list), 'invalid dataset category/pages')
            require(type(dataset.get('series')) is int and type(dataset.get('eligible')) is int and 0 <= dataset['eligible'] <= dataset['series'], 'invalid dataset counts')
            for page in dataset['pages']:
                require(isinstance(page, dict) and set(page) == {'path', 'bytes', 'sha256', 'rows'}, 'invalid catalogue page fields')
                require(isinstance(page['path'], str) and page['path'] and page['path'] not in seen_pages, 'duplicate/invalid catalogue page')
                seen_pages.add(page['path'])
                require(type(page['bytes']) is int and page['bytes'] > 0 and type(page['rows']) is int and page['rows'] >= 0, 'invalid catalogue page counts')
                require(isinstance(page['sha256'], str) and re.fullmatch('[0-9a-f]{64}', page['sha256']), 'invalid catalogue hash')
                Hub.catalogue_page(path, page)
            require(sum(page['rows'] for page in dataset['pages']) == dataset['series'], 'catalogue row totals mismatch')
        return path, hashlib.sha256(raw).hexdigest(), data

    def split(self, manifest, assignment='lead', batch_size=500):
        require(not self.self_service(), 'split before enabling self-service; automatic batch allocation disabled')
        require(assignment in ('lead', 'balanced'), 'invalid assignment policy')
        require(type(batch_size) is int and 1 <= batch_size <= 500, 'batch size must be between 1 and 500')
        manifest, manifest_hash, catalogue = self.manifest(manifest)
        request = dict(manifest_path=str(manifest), manifest_sha256=manifest_hash,
                       assignment=assignment, batch_size=batch_size)
        created, activated, deferred = 0, [], []
        with self.coordinator():
            plans = self.batch_plans()
            for plan in plans.values():
                require(all(plan[key] == value for key, value in request.items()), 'existing batch policy/manifest differs; manual reconciliation required')
            tasks = self.tasks()
            candidates = []
            for task in tasks:
                if task['kind'] != 'triage' or 'batch_spec' in task or task['id'] in plans:
                    continue
                datasets = [d for d in catalogue['datasets'] if d['type'] == task['category'] and d['eligible'] < d['series']]
                if not datasets:
                    continue
                if self.state(task, plans)[0] != 'queued':
                    deferred.append(task['id'])
                    continue
                slices = [(d['id'], page, start, min(start + batch_size, page['rows']))
                          for d in datasets for page in d['pages'] for start in range(0, page['rows'], batch_size)]
                if slices:
                    if 'audit_utc' in task:
                        require(isinstance(catalogue.get('auditUtc'), str) and
                                instant(catalogue['auditUtc']) == instant(task['audit_utc']),
                                'catalogue audit epoch differs from parent')
                    candidates.append((task, slices))
            require(len(tasks) + sum(len(slices) for _, slices in candidates) <= 20000, 'public task cap exceeded')
            candidate_ids = {task['id'] for task, _ in candidates}
            loads = dict.fromkeys(PEOPLE, 0)
            for task in tasks:
                if task['id'] not in candidate_ids and task['kind'] == 'triage' and self.state(task, plans)[0] not in ('verified', 'batched'):
                    loads[task['assignee']] += task['affected_series']
            directory = self.root / 'batch-plans'
            directory.mkdir(exist_ok=True, mode=0o755)
            os.chmod(directory, 0o755)
            self.protected(directory)
            for candidate_index, (parent, slices) in enumerate(candidates):
                parent_id = parent['id']
                incoming = directory / ('.' + parent_id + '.incoming')
                incoming.mkdir(mode=0o755)
                os.chmod(incoming, 0o755)
                staged_tasks = incoming / 'tasks'
                staged_tasks.mkdir(mode=0o755)
                os.chmod(staged_tasks, 0o755)
                prefix = 'batch-' + digest(parent)[:24] + '-'
                at = now()
                plan = dict(request, parent_id=parent_id, parent_sha256=digest(parent),
                            child_prefix=prefix, batch_total=len(slices), activated_at=at)
                for number, (dataset_id, page, start, stop) in enumerate(slices, 1):
                    assignee = parent['assignee']
                    if assignment == 'balanced':
                        assignee = min(PEOPLE, key=lambda p: loads[p])
                    count = stop - start
                    loads[assignee] += count
                    child = dict(parent, id=prefix + f'{number:06d}', assignee=assignee,
                                 lead=parent['assignee'], parent_id=parent_id, batch_number=number,
                                 batch_total=len(slices), affected_series=count, effort=min(5, (count + 99) // 100),
                                 created_at=at, batch_spec=dict(manifest_path=str(manifest), manifest_sha256=manifest_hash,
                                                              dataset_id=dataset_id, page=page, start=start, stop=stop))
                    write(staged_tasks / (child['id'] + '.json'), child)
                write(incoming / 'plan.json', plan)
                claim = self.root / 'claims' / parent_id
                try:
                    claim.mkdir(mode=0o755)
                except FileExistsError:
                    # A worker won the exclusive legacy claim while we staged.
                    shutil.rmtree(incoming)
                    deferred.append(parent_id)
                    # Recompute once after a race so subsequent packing reflects real work.
                    loads = self.review_loads()
                    for pending, _ in candidates[candidate_index + 1:]:
                        loads[pending['assignee']] -= pending['affected_series']
                    continue
                os.chmod(claim, 0o755)
                write(claim / 'owner.json', dict(person=parent['assignee'], uid=os.getuid(),
                                                task_sha256=digest(parent), claimed_at=at))
                require(digest(self.task(parent_id)) == digest(parent), 'parent changed during migration; reconcile manually')
                os.rename(incoming, directory / parent_id)
                created += len(slices)
                activated.append(parent_id)
        return dict(created=created, activated=activated, deferred=deferred)

    def review_loads(self):
        require(not self.self_service(), 'historical allocation loads disabled in self-service mode')
        plans = self.batch_plans()
        loads = dict.fromkeys(PEOPLE, 0)
        for task in self.tasks():
            if task['kind'] == 'triage' and self.state(task, plans)[0] not in ('verified', 'batched'):
                loads[task['assignee']] += task['affected_series']
        return loads

    def read_batch(self, task_id):
        task = self.task(task_id)
        spec = task.get('batch_spec')
        require(isinstance(spec, dict), 'task is not a review batch')
        manifest, sha256, data = self.manifest(spec['manifest_path'])
        require(sha256 == spec['manifest_sha256'], 'manifest hash mismatch')
        datasets = [d for d in data['datasets'] if d['id'] == spec['dataset_id']]
        require(len(datasets) == 1 and datasets[0]['type'] == task['category'] and spec['page'] in datasets[0]['pages'], 'batch selector not in pinned manifest')
        page = spec['page']
        start, stop = spec['start'], spec['stop']
        require(type(start) is int and type(stop) is int and 0 <= start < stop <= page['rows'] and stop - start <= 500, 'invalid batch selector')
        path = self.catalogue_page(manifest, page)
        limit = 32 * 1024 * 1024
        require(not path.is_symlink() and path.stat().st_size == page['bytes'] and page['bytes'] <= limit, 'page size mismatch or too large')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == page['sha256'], 'page hash mismatch')
        # gzip.read has an explicit decoded limit; never materialize an unbounded page.
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(limit + 1)
        require(len(decoded) <= limit, 'decoded page exceeds 32 MiB')
        payload = json.loads(decoded)
        require(payload.get('schema') == 'kuina-series-page-v1' and payload.get('datasetId') == spec['dataset_id'], 'page identity mismatch')
        rows = payload.get('series')
        require(isinstance(rows, list) and len(rows) == page['rows'], 'page row count mismatch')
        selected = rows[start:stop]
        require(all(isinstance(row, dict) and row.get('decision') in ('ELIGIBLE', 'INELIGIBLE') for row in selected), 'unknown catalogue eligibility decision')
        records = [row for row in selected if row['decision'] == 'INELIGIBLE']
        return dict(task_id=task_id, selected=len(selected), skipped_eligible=len(selected) - len(records), records=records)

    def listing(self, person=None, limit=20, offset=0, all_tasks=False, available=False, category=None):
        require(type(limit) is int and limit > 0 and type(offset) is int and offset >= 0, 'invalid pagination')
        require(person is None or person in PEOPLE, 'unknown person')
        require(category is None or category in IDS, 'unknown category')
        plans = self.batch_plans()
        rows = []
        priority = {'active': 0, 'blocked': 1, 'awaiting_verification': 2, 'assigned': 3, 'available': 4, 'queued': 4, 'verified': 5, 'batched': 6}
        for task in self.tasks():
            status, updated = self.state(task, plans)
            if person and self.effective_assignee(task, plans) != person:
                continue
            if available and status != 'available':
                continue
            if category and task['category'] != category:
                continue
            if not all_tasks and status in ('verified', 'batched'):
                continue
            rows.append(self.task_view(task, plans))
        rows.sort(key=lambda row: (priority[row['status']], row['created_at'], row['id']))
        return rows[offset:] if all_tasks else rows[offset:offset + limit]

    def self_service_snapshot(self):
        plans = self.batch_plans()
        people = {p: dict(id=p, name=name, assigned=0, active=0, awaiting_verification=0,
                          verified=0, remaining_series=0) for p, name in PEOPLE.items()}
        tasks = []
        for task in self.tasks():
            status, updated = self.state(task, plans)
            person = self.effective_assignee(task, plans)
            record = self.reservation(task) if status != 'batched' else None
            row = {key: task[key] for key in ('id', 'category', 'kind', 'affected_series', 'created_at')}
            row.update(status=status, updated_at=updated, assignee=person,
                       issues=[i for i in task['issues'] if i in FULL_ISSUES],
                       parent_id=task.get('parent_id'), batch_number=task.get('batch_number', 0),
                       batch_total=task.get('batch_total', plans.get(task['id'], {}).get('batch_total', 0)),
                       assignment_issue=record['current']['issue'] if record and record['current'] else None)
            tasks.append(row)
            if person is not None:
                people[person]['active' if status == 'blocked' else status] += 1
                if status != 'verified' and task['kind'] == 'triage':
                    people[person]['remaining_series'] += task['affected_series']
        return validate_public_snapshot(dict(schema_version=3, updated_at=now(), profile=PROFILE,
                                             people=list(people.values()), tasks=tasks, batch_limit=500))

    def snapshot(self):
        if self.self_service():
            return self.self_service_snapshot()
        plans = self.batch_plans()
        version = 2 if plans else 1
        people = {p: dict(id=p, name=name, queued=0, active=0, awaiting_verification=0, verified=0, load=0)
                  for p, name in PEOPLE.items()}
        if plans:
            for person in people.values():
                person.update(batched=0, remaining_series=0)
        all_tasks = self.tasks()
        leads = {task['category']: task['assignee'] for task in all_tasks
                 if task['kind'] == 'triage' and 'batch_spec' not in task}
        tasks = []
        for task in all_tasks:
            status, updated = self.state(task, plans)
            row = {key: task[key] for key in ('id', 'category', 'kind', 'assignee', 'effort', 'affected_series', 'created_at')}
            row.update(status=status, updated_at=updated, issues=[i for i in task['issues'] if i in FULL_ISSUES])
            if plans:
                lead = task.get('lead', leads.get(task['category'], task['assignee']))
                if task['kind'] == 'triage' and 'batch_spec' not in task:
                    lead = task['assignee']
                row.update(lead=lead,
                           parent_id=task.get('parent_id'), batch_number=task.get('batch_number', 0),
                           batch_total=task.get('batch_total', plans.get(task['id'], {}).get('batch_total', 0)))
            tasks.append(row)
            person = people[task['assignee']]
            person['active' if status == 'blocked' else status] += 1
            if status not in ('verified', 'batched'):
                person['load'] += task['effort']
                if plans and task['kind'] == 'triage':
                    person['remaining_series'] += task['affected_series']
        snapshot = {'schema_version': version, 'updated_at': now(), 'profile': PROFILE,
                    'people': list(people.values()), 'tasks': tasks}
        if plans:
            snapshot['batch_limit'] = 500
        return validate_public_snapshot(snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hub', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('enable-self-service')
    commands.add_parser('seed').add_argument('--summary', required=True, type=Path)
    listing = commands.add_parser('list')
    listing.add_argument('--person', choices=PEOPLE)
    listing.add_argument('--available', action='store_true')
    listing.add_argument('--category', choices=IDS)
    listing.add_argument('--limit', type=int, default=20)
    listing.add_argument('--offset', type=int, default=0)
    listing.add_argument('--all', action='store_true')
    commands.add_parser('show').add_argument('task')
    commands.add_parser('assignment-status').add_argument('task')
    request = commands.add_parser('request-status')
    request.add_argument('task')
    request.add_argument('--issue', required=True, type=int)
    commands.add_parser('read-batch').add_argument('task')
    split = commands.add_parser('split')
    split.add_argument('--manifest', required=True, type=Path)
    split.add_argument('--assignment', required=True, choices=('lead', 'balanced'))
    split.add_argument('--batch-size', type=int, default=500)
    for command in ('assign', 'release-assignment'):
        assignment = commands.add_parser(command)
        assignment.add_argument('task')
        assignment.add_argument('--person', required=True, choices=PEOPLE)
        assignment.add_argument('--github-author', required=True)
        if command == 'assign':
            assignment.add_argument('--issue', required=True, type=int)
        else:
            assignment.add_argument('--coordinator', action='store_true')
            assignment.add_argument('--request-issue', type=int)
            assignment.add_argument('--assignment-issue', type=int)
    claim = commands.add_parser('claim')
    claim.add_argument('task')
    claim.add_argument('--person', required=True, choices=PEOPLE)
    report = commands.add_parser('report')
    report.add_argument('task')
    report.add_argument('--person', required=True, choices=PEOPLE)
    report.add_argument('--status', required=True, choices=('in_progress', 'blocked', 'completed'))
    report.add_argument('--note', required=True)
    proposal = commands.add_parser('propose')
    proposal.add_argument('--file', required=True, type=Path)
    proposal.add_argument('--person', required=True, choices=PEOPLE)
    commands.add_parser('admit').add_argument('--proposal', required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('task')
    verify.add_argument('--receipt', required=True, type=Path)
    commands.add_parser('snapshot').add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    hub = Hub(args.hub)
    try:
        if args.command == 'init':
            result = hub.init()
        elif args.command == 'enable-self-service':
            result = hub.enable_self_service()
        elif args.command == 'assign':
            result = hub.assign(args.task, args.person, args.issue, args.github_author)
        elif args.command == 'release-assignment':
            result = hub.release_assignment(args.task, args.person, args.github_author, args.coordinator,
                                            args.request_issue, args.assignment_issue)
        elif args.command == 'seed':
            result = hub.seed(read(args.summary))
        elif args.command == 'list':
            result = hub.listing(args.person, args.limit, args.offset, args.all, args.available, args.category)
        elif args.command == 'assignment-status':
            result = hub.assignment_status(args.task)
        elif args.command == 'request-status':
            result = hub.request_status(args.task, args.issue)
        elif args.command == 'show':
            result = hub.show(args.task)
        elif args.command == 'read-batch':
            result = hub.read_batch(args.task)
        elif args.command == 'split':
            result = hub.split(args.manifest, args.assignment, args.batch_size)
        elif args.command == 'claim':
            result = hub.claim(args.task, args.person)
        elif args.command == 'report':
            result = hub.report(args.task, args.person, args.status, args.note)
        elif args.command == 'propose':
            result = hub.propose(read(args.file), args.person)
        elif args.command == 'admit':
            result = hub.admit(args.proposal)
        elif args.command == 'verify':
            result = hub.verify(args.task, read(args.receipt))
        else:
            result = hub.snapshot()
            write(args.output, result)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()

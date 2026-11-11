#!/usr/bin/env python3
"""Private shared-filesystem coordination; never executes collection instructions."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
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
    require(isinstance(data, dict) and set(data) == {'schema_version', 'updated_at', 'profile', 'people', 'tasks'}, 'invalid snapshot fields')
    require(type(data['schema_version']) is int and data['schema_version'] == 1, 'invalid snapshot version')
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
    require(isinstance(data['tasks'], list) and len(data['tasks']) <= 10000, 'invalid public task list')
    seen = set()
    for task in data['tasks']:
        require(isinstance(task, dict) and set(task) == {'id', 'category', 'kind', 'status', 'assignee', 'effort', 'affected_series', 'issues', 'created_at', 'updated_at'}, 'invalid public task fields')
        identifier(task['id'])
        require(task['id'] not in seen, 'duplicate task ID')
        seen.add(task['id'])
        require(task['category'] in IDS and task['kind'] in KINDS and task['assignee'] in PEOPLE, 'invalid public task category/kind/person')
        require(task['status'] in ('queued', 'active', 'blocked', 'awaiting_verification', 'verified'), 'invalid public task status')
        number(task['effort'], 100)
        require(task['effort'] > 0, 'effort must be positive')
        number(task['affected_series'])
        require(isinstance(task['issues'], list) and len(task['issues']) <= len(FULL_ISSUES) and all(isinstance(i, str) and i in FULL_ISSUES for i in task['issues']), 'invalid public reasons')
        require(len(set(task['issues'])) == len(task['issues']), 'duplicate public reasons')
        timestamp(task['created_at'])
        timestamp(task['updated_at'])
        person = expected[task['assignee']]
        person['active' if task['status'] == 'blocked' else task['status']] += 1
        if task['status'] != 'verified':
            person['load'] += task['effort']
    seen_people = set()
    for person in data['people']:
        require(isinstance(person, dict) and set(person) == {'id', 'name', 'queued', 'active', 'awaiting_verification', 'verified', 'load'}, 'invalid public person fields')
        require(isinstance(person['id'], str) and person['id'] in PEOPLE and person['id'] not in seen_people, 'invalid public person')
        seen_people.add(person['id'])
        for key in ('queued', 'active', 'awaiting_verification', 'verified', 'load'):
            number(person[key])
        require(person == expected[person['id']], 'public person totals/name mismatch')
    return data


class Hub:
    def __init__(self, root):
        self.root = Path(root).absolute()

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

    def task(self, task_id):
        path = self.root / 'tasks' / (identifier(task_id) + '.json')
        self.protected(path)
        task = read(path)
        require(task['id'] == task_id, 'task ID mismatch')
        return task

    def tasks(self):
        return [self.task(p.stem) for p in sorted((self.root / 'tasks').glob('*.json'))]

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

    def state(self, task):
        receipt = self.root / 'verified' / (task['id'] + '.json')
        if receipt.exists():
            self.protected(receipt)
            require(read(receipt)['task_sha256'] == digest(task), 'verification task hash mismatch')
            return 'verified', read(receipt)['verified_at']
        claim = self.root / 'claims' / task['id']
        if not claim.exists():
            return 'queued', task['created_at']
        path, owner = self.claim_record(task)
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
        loads = dict.fromkeys(PEOPLE, 0)
        for task in self.tasks():
            if self.state(task)[0] != 'verified':
                loads[task['assignee']] += task['effort']
        return loads

    def assign(self):
        loads = self.loads()
        return min(PEOPLE, key=lambda p: (loads[p], list(PEOPLE).index(p)))

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
                        'assignee': self.assign(), 'effort': 1, 'affected_series': category['excluded_series'],
                        'issues': [i['id'] for i in category['issues'] if i['count']],
                        'issue_totals': category['issues'], 'source_failures': category['source_failures'],
                        'audit_utc': summary['audit_utc'], 'assessment_utc': summary['assessment_utc'],
                        'created_at': now(), 'scope': None}
                write(self.root / 'tasks' / (task_id + '.json'), task)
                created.append(task_id)
        return created

    def claim(self, task_id, person):
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
        path, owner = self.claim_record(task)
        require(owner['uid'] == os.getuid() and owner['person'] == person, 'only actual claim owner may report')
        lock = path / '.report-lock'
        lock.mkdir()
        try:
            require(self.state(task)[0] not in ('verified', 'awaiting_verification'), 'task completion is final pending coordinator review')
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
            task = dict(proposal, id=task_id, assignee=self.assign(), created_at=now())
            write(self.root / 'tasks' / (task_id + '.json'), task)
            return {'admitted': True, 'task_id': task_id}

    def validate_admission(self, proposal):
        allowed = {'category', 'kind', 'effort', 'affected_series', 'issues', 'scope', 'preflight'}
        require(isinstance(proposal, dict) and set(proposal) <= allowed and allowed - {'preflight'} <= set(proposal), 'unexpected proposal fields')
        require(proposal['category'] in IDS and proposal['kind'] in KINDS - {'triage'}, 'invalid proposal category/kind')
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

    def snapshot(self):
        people = {p: dict(id=p, name=name, queued=0, active=0, awaiting_verification=0, verified=0, load=0)
                  for p, name in PEOPLE.items()}
        tasks = []
        for task in self.tasks():
            status, updated = self.state(task)
            row = {key: task[key] for key in ('id', 'category', 'kind', 'assignee', 'effort', 'affected_series', 'created_at')}
            row.update(status=status, updated_at=updated, issues=[i for i in task['issues'] if i in FULL_ISSUES])
            tasks.append(row)
            person = people[task['assignee']]
            person['active' if status == 'blocked' else status] += 1
            if status != 'verified':
                person['load'] += task['effort']
        return validate_public_snapshot({'schema_version': 1, 'updated_at': now(), 'profile': PROFILE,
                                         'people': list(people.values()), 'tasks': tasks})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hub', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('seed').add_argument('--summary', required=True, type=Path)
    commands.add_parser('list').add_argument('--person', choices=PEOPLE)
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
        elif args.command == 'seed':
            result = hub.seed(read(args.summary))
        elif args.command == 'list':
            result = []
            for task in hub.tasks():
                status, updated_at = hub.state(task)
                result.append(dict(task, status=status, updated_at=updated_at, task_sha256=digest(task)))
            if args.person:
                result = [t for t in result if t['assignee'] == args.person]
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

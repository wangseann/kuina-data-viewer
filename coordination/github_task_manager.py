#!/usr/bin/env python3
"""Private GitHub-authorized work CLI; never creates authority pointers or calls GitHub.

The coordinator installs a protected github-assignment-authority.json separately.
Legacy workers retain show/read-batch/report. New starts require the observed
GitHub working permit and the actual UID-bound preparation proof.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordination.task_manager import Hub, PEOPLE, instant, now, require
from coordination.unique_queue import closed, file_bytes, parse, safe_path
from coordination.github_legacy import LegacyCatalogue, CombinedWorkProtocol
from coordination.github_work import encoded, exclusive_write, sha
from coordination.github_assignments import record as validate_assignment

REPO = 'wangseann/kuina-data-viewer'
HASH = re.compile(r'[0-9a-f]{64}')
REPORT_FIELDS = ('schema', 'uid', 'person', 'batch_sha256', 'preparation_sha256', 'at', 'status', 'note')


def bounded_json(raw):
    require(isinstance(raw, str) and len(raw.encode()) <= 16384, 'Bounded JSON argument required')
    value = parse(raw)
    require(type(value) is dict, 'JSON object required')
    return value


class Manager:
    def __init__(self, hub_root):
        self.legacy = Hub(hub_root)

    def catalogue(self):
        root = safe_path(self.legacy.root)
        info = root.stat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'Unprotected hub root')
        config = parse(file_bytes(root / 'github-assignment-authority.json', 4096, info.st_uid))
        closed(config, ('schema', 'queue_root', 'generation', 'repo'))
        require(config['schema'] == 'kuina-private-github-authority-v1' and config['repo'] == REPO
                and isinstance(config['generation'], str) and HASH.fullmatch(config['generation'])
                and isinstance(config['queue_root'], str) and Path(config['queue_root']).is_absolute(),
                'Invalid protected GitHub authority')
        queue = safe_path(config['queue_root'])
        require(root / 'unique-work' in queue.parents, 'Queue must be below hub unique-work')
        for directory in (queue, *queue.parents):
            entry = directory.stat()
            require(stat.S_ISDIR(entry.st_mode) and entry.st_uid == info.st_uid and not entry.st_mode & 0o022,
                    'Unprotected authority queue ancestor')
            if directory == root:
                break
        return LegacyCatalogue(queue, self.legacy, config['generation'])

    def protocol(self):
        return CombinedWorkProtocol(self.catalogue())

    def guard(self, batch_id, action, assignment=None, proof_sha256=None):
        catalogue = self.catalogue()
        if assignment is not None:
            validate_assignment(assignment)
            row = catalogue.row(batch_id)
            require(assignment['batch_id'] == batch_id and assignment['catalogue_generation'] == catalogue.generation
                    and assignment['definition_sha256'] == row['file']['sha256'], 'Assignment generation/scope differs')
        return catalogue.guard(batch_id, action, assignment, proof_sha256)

    def prepare_work(self, batch_id, person, assignment_issue):
        result = self.protocol().prepare(batch_id, person, assignment_issue)
        payload = dict(version=1, action='working', task_id=batch_id, person=person,
                       assignment_issue=assignment_issue, proof_sha256=result['proof_sha256'])
        body = '<!-- kuina-request-v1\n' + json.dumps(payload, separators=(',', ':')) + '\n-->'
        return dict(result, github_start_url='https://github.com/' + REPO + '/issues/new?' +
                    urlencode(dict(title='[Kuina start] ' + batch_id, body=body)))

    def authorize(self, authorization):
        return self.protocol().authorize(authorization)

    def claim(self, proof_sha256):
        return self.protocol().claim(proof_sha256)

    def read_batch(self, batch_id):
        if not batch_id.startswith('unique-'):
            return self.legacy.read_batch(batch_id)
        return self.catalogue().read_batch(batch_id)

    def worker_state(self, catalogue, row, own_report_lock=False):
        path = safe_path(self.legacy.shared_directory('work-claims') / row['id'])
        if not path.exists():
            return path, None, 'no_private_worker_proof'
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'Unprotected actual worker')
        owner = parse(file_bytes(path / 'owner.json', 8192, info.st_uid))
        closed(owner, ('schema', 'uid', 'person', 'task_sha256', 'claimed_at', 'preparation_sha256', 'authorization_sha256'))
        require(owner['schema'] == 'kuina-github-private-worker-v1' and type(owner['uid']) is int
                and owner['uid'] == info.st_uid and owner['person'] in PEOPLE
                and owner['task_sha256'] == row['file']['sha256'] and instant(owner['claimed_at']) <= instant(now())
                and all(isinstance(owner[k], str) and HASH.fullmatch(owner[k])
                        for k in ('preparation_sha256', 'authorization_sha256')), 'Actual worker proof differs')
        protocol = CombinedWorkProtocol(catalogue)
        token = parse(file_bytes(protocol.preparation_path(owner['preparation_sha256']), 8192, owner['uid']))
        prepared = protocol.verify(row['id'], owner['person'], token['assignment_issue'], owner['preparation_sha256'])
        require(prepared['uid'] == owner['uid'] and instant(prepared['prepared_at']) <= instant(owner['claimed_at']),
                'Actual UID or preparation time differs')
        raw = file_bytes(protocol.authorization_path(row['id']), 8192, self.legacy.root.stat().st_uid)
        authorization = parse(raw)
        protocol.validate_authorization(authorization)
        require(authorization['proof_sha256'] == owner['preparation_sha256']
                and sha(raw) == owner['authorization_sha256'], 'Actual observed permit differs')
        reports = []
        for entry in path.iterdir():
            if entry.name == 'owner.json':
                continue
            if entry.name == '.report-lock':
                require(own_report_lock, 'Interrupted report; reconcile manually')
                continue
            require(re.fullmatch(r'report-[0-9a-f]{32}[.]json', entry.name), 'Unknown worker journal; reconcile manually')
            report = parse(file_bytes(entry, 16384, owner['uid']))
            closed(report, REPORT_FIELDS)
            require(report['schema'] == 'kuina-github-private-report-v1'
                    and type(report['uid']) is int and report['uid'] == owner['uid'] and report['person'] == owner['person']
                    and report['batch_sha256'] == owner['task_sha256']
                    and report['preparation_sha256'] == owner['preparation_sha256']
                    and report['status'] in ('active', 'blocked', 'awaiting_verification')
                    and isinstance(report['note'], str) and 0 < len(report['note'].strip()) <= 4000
                    and instant(owner['claimed_at']) <= instant(report['at']) <= instant(now()), 'Private report proof differs')
            reports.append(report)
        reports.sort(key=lambda value: instant(value['at']))
        require(not any(value['status'] == 'awaiting_verification' for value in reports[:-1]), 'Report follows final completion')
        return path, owner, reports[-1]['status'] if reports else 'active'

    def show(self, batch_id):
        if not batch_id.startswith('unique-'):
            return self.legacy.show(batch_id)
        catalogue = self.catalogue()
        row = catalogue.row(batch_id)
        _, owner, status = self.worker_state(catalogue, row)
        return dict(id=batch_id, category=row['category'], target_count=row['target_count'],
                    series_count=row['series_count'], status=status, worker=owner,
                    assignment_authority='GitHub; absent private proof does not release working reservation')

    def report(self, batch_id, person, status, note):
        if not batch_id.startswith('unique-'):
            return self.legacy.report(batch_id, person, status, note)
        require(person in PEOPLE and status in ('in_progress', 'blocked', 'completed')
                and isinstance(note, str) and 0 < len(note.strip()) <= 4000, 'Valid private report required')
        catalogue = self.catalogue()
        row = catalogue.row(batch_id)
        path, owner, current = self.worker_state(catalogue, row)
        require(owner is not None and owner['uid'] == os.getuid() and owner['person'] == person,
                'Only actual UID/person may report')
        require(current != 'awaiting_verification', 'Completion is final pending independent review')
        lock = path / '.report-lock'
        lock.mkdir(mode=0o755)
        uncertain = True
        try:
            _, latest, current = self.worker_state(catalogue, row, own_report_lock=True)
            require(latest == owner and current != 'awaiting_verification', 'Worker changed during report')
            report = dict(schema='kuina-github-private-report-v1', uid=owner['uid'], person=person,
                          batch_sha256=owner['task_sha256'], preparation_sha256=owner['preparation_sha256'], at=now(),
                          status={'in_progress': 'active', 'blocked': 'blocked', 'completed': 'awaiting_verification'}[status], note=note.strip())
            exclusive_write(path / ('report-' + uuid.uuid4().hex + '.json'), encoded(report))
            require(self.worker_state(catalogue, row, own_report_lock=True)[2] == report['status'], 'Report not observed')
            uncertain = False
            return report
        finally:
            if not uncertain:
                lock.rmdir()  # Unknown interruptions retain the lock and journal.


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--hub', required=True, type=Path)
    commands = value.add_subparsers(dest='command', required=True)
    guard = commands.add_parser('github-guard')
    guard.add_argument('batch')
    guard.add_argument('--action', required=True, choices=('assign', 'release', 'working'))
    guard.add_argument('--assignment', type=bounded_json)
    guard.add_argument('--proof-sha256')
    prepare = commands.add_parser('prepare-work')
    prepare.add_argument('batch')
    prepare.add_argument('--person', choices=PEOPLE, required=True)
    prepare.add_argument('--assignment-issue', type=int, required=True)
    authorize = commands.add_parser('authorize-github-work')
    authorize.add_argument('--authorization', type=bounded_json, required=True)
    claim = commands.add_parser('claim')
    claim.add_argument('--proof-sha256', required=True)
    for name in ('show', 'read-batch'):
        commands.add_parser(name).add_argument('batch')
    report = commands.add_parser('report')
    report.add_argument('batch')
    report.add_argument('--person', choices=PEOPLE, required=True)
    report.add_argument('--status', choices=('in_progress', 'blocked', 'completed'), required=True)
    report.add_argument('--note', required=True)
    return value


def dispatch(args):
    manager = Manager(args.hub)
    if args.command == 'github-guard':
        return manager.guard(args.batch, args.action, args.assignment, args.proof_sha256)
    if args.command == 'prepare-work':
        return manager.prepare_work(args.batch, args.person, args.assignment_issue)
    if args.command == 'authorize-github-work':
        return manager.authorize(args.authorization)
    if args.command == 'claim':
        return manager.claim(args.proof_sha256)
    if args.command == 'report':
        return manager.report(args.batch, args.person, args.status, args.note)
    if args.command == 'read-batch':
        return manager.read_batch(args.batch)
    return manager.show(args.batch)


def main():
    arguments = parser()
    try:
        print(json.dumps(dispatch(arguments.parse_args()), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        arguments.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()

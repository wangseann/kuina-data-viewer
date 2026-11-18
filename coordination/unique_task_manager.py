#!/usr/bin/env python3
"""Private wrapper for additive unique work and unchanged legacy Hub operations.

An owner-protected HUB/unique-work.json opts into the queue with the closed
schema {schema_version: 1, queue_root: absolute canonical descendant of
HUB/unique-work, manifest_sha256: SHA256}. This module never installs a pointer.
Queue IDs must start with unique-. Existing IDs keep their original interfaces.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordination.task_manager import Hub, IDS, PEOPLE, now, require, write
from coordination.unique_queue import (UniqueQueue, MAX_MANIFEST_BYTES, closed,
                                      file_bytes, manifest_rows, parse, safe_path, sha)
from unique_dashboard import TASK_SCHEMA, STATUSES, validate as validate_publication


class Manager:
    def __init__(self, hub_root):
        self.legacy = Hub(hub_root)

    def queue(self):
        root = safe_path(self.legacy.root)
        info = root.stat()
        require(not info.st_mode & 0o022, 'unsafe legacy hub root')
        pointer = safe_path(root/'unique-work.json')
        if not pointer.exists():
            return None
        config = parse(file_bytes(pointer, 4096, info.st_uid))
        closed(config, ('schema_version', 'queue_root', 'manifest_sha256'))
        require(type(config['schema_version']) is int and config['schema_version'] == 1 and
                isinstance(config['queue_root'], str) and Path(config['queue_root']).is_absolute(),
                'invalid unique queue pointer')
        destination = safe_path(config['queue_root'])
        require(destination.is_absolute() and root/'unique-work' in destination.parents,
                'unique queue root must be below canonical hub unique-work directory')
        for directory in (destination, *destination.parents):
            entry = directory.stat()
            require(entry.st_uid == info.st_uid and not entry.st_mode & 0o022,
                    'queue pointer ancestor ownership/mode mismatch')
            if directory == root:
                break
        queue = UniqueQueue(destination, self.legacy)
        installed, owner = queue.configuration()
        require(installed['manifest_sha256'] == config['manifest_sha256'], 'pointer manifest hash mismatch')
        raw = file_bytes(destination/'package/manifest.json', MAX_MANIFEST_BYTES, owner)
        require(sha(raw) == config['manifest_sha256'], 'installed manifest hash mismatch')
        rows = manifest_rows(parse(raw))
        require(all(row['id'].startswith('unique-') for row in rows), 'unique queue batch IDs require unique- prefix')
        return queue

    def target(self, task_id):
        if task_id.startswith('unique-'):
            queue = self.queue()
            if queue is not None:
                return queue
        return self.legacy

    def show(self, task_id):
        return self.target(task_id).show(task_id)

    def read_batch(self, task_id):
        target = self.target(task_id)
        if isinstance(target, UniqueQueue):
            return target.read(task_id)
        return target.read_batch(task_id)

    def claim(self, task_id, person):
        return self.target(task_id).claim(task_id, person)

    def report(self, task_id, person, status, note):
        return self.target(task_id).report(task_id, person, status, note)

    def assign(self, task_id, person, issue, github_author):
        return self.target(task_id).assign(task_id, person, issue, github_author)

    def release_assignment(self, task_id, person, github_author, coordinator=False,
                           request_issue=None, assignment_issue=None):
        return self.target(task_id).release_assignment(task_id, person, github_author, coordinator,
                                                      request_issue, assignment_issue)

    def assignment_status(self, task_id):
        return self.target(task_id).assignment_status(task_id)

    def request_status(self, task_id, issue):
        return self.target(task_id).request_status(task_id, issue)

    @staticmethod
    def queue_views(queue):
        return queue.snapshot()

    def listing(self, person=None, limit=20, offset=0, all_tasks=False,
                available=False, category=None, include_legacy=False):
        require(type(limit) is int and limit > 0 and type(offset) is int and offset >= 0, 'invalid pagination')
        require(person is None or person in PEOPLE, 'unknown person')
        require(category is None or category in IDS, 'unknown category')
        queue = self.queue()
        if queue is None:
            return self.legacy.listing(person, limit, offset, all_tasks, available, category)
        rows = self.queue_views(queue)
        if include_legacy:
            rows.extend(self.legacy.listing(all_tasks=True))
        rows = [row for row in rows if (person is None or row['assignee'] == person) and
                (category is None or row['category'] == category) and
                (not available or row['status'] == 'available') and
                (all_tasks or row['status'] not in ('verified', 'batched'))]
        priority = {'active':0, 'blocked':1, 'awaiting_verification':2, 'assigned':3,
                    'available':4, 'queued':4, 'verified':5, 'batched':6}
        rows.sort(key=lambda row: (priority[row['status']], row['id']))
        return rows[offset:] if all_tasks else rows[offset:offset+limit]

    def unique_snapshot(self):
        """Closed approved dashboard task metadata. No private notes or identifiers."""
        queue = self.queue()
        require(queue is not None, 'unique queue pointer required')
        return self._unique_snapshot(queue)

    def _unique_snapshot(self, queue):
        batches = []
        for row in self.queue_views(queue):
            require(row['status'] in STATUSES, 'unsupported public unique status')
            batches.append(dict(id=row['id'], category=row['category'], target_count=row['target_count'],
                                series_count=row['series_count'], status=row['status'], assignee=row['assignee'],
                                assignment_issue=row['assignment_issue'],
                                blocker_codes=['legacy_reservation'] if row['legacy_blockers'] else []))
        result = dict(schema=TASK_SCHEMA, generated_at=now().replace('+00:00', 'Z'),
                      people=[dict(id=person, name=name) for person, name in PEOPLE.items()], batches=batches)
        require(len(batches) <= 20000 and len(json.dumps(result).encode()) <= 8 * 1024 * 1024,
                'unique public snapshot bound exceeded')
        return result

    def publication_snapshot(self):
        """Private publisher envelope bound to one protected queue generation."""
        hub = safe_path(self.legacy.root)
        coordinator = hub.stat().st_uid
        pointer = hub/'unique-work.json'
        pointer_raw = file_bytes(pointer, 4096, coordinator)
        queue = self.queue()
        require(queue is not None, 'unique queue pointer required')
        config, owner = queue.configuration()
        selected = parse(pointer_raw)
        closed(selected, ('schema_version', 'queue_root', 'manifest_sha256'))
        require(type(selected['schema_version']) is int and selected['schema_version'] == 1 and
                selected['queue_root'] == str(queue.root) and selected['manifest_sha256'] == config['manifest_sha256'],
                'unique queue pointer changed before publication selection')
        publication_path = queue.root/'publication.json'
        publication_raw = file_bytes(publication_path, 128*1024, owner)
        publication = parse(publication_raw)
        closed(publication, ('schema', 'manifest_sha256', 'summary'))
        require(publication['schema'] == 'kuina-unique-publication-v1' and
                publication['manifest_sha256'] == config['manifest_sha256'],
                'publication queue manifest mismatch')
        tasks = self._unique_snapshot(queue)
        validate_publication(publication['summary'], tasks)
        require(file_bytes(publication_path, 128*1024, owner) == publication_raw,
                'publication record changed during snapshot')
        require(queue.configuration() == (config, owner), 'queue configuration changed during publication')
        require(file_bytes(pointer, 4096, coordinator) == pointer_raw,
                'unique queue pointer changed during publication')
        queue.require_idle()
        return dict(queue_manifest_sha256=config['manifest_sha256'], summary=publication['summary'], tasks=tasks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hub', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list')
    listing.add_argument('--person', choices=PEOPLE)
    listing.add_argument('--available', action='store_true')
    listing.add_argument('--category', choices=IDS)
    listing.add_argument('--limit', type=int, default=20)
    listing.add_argument('--offset', type=int, default=0)
    listing.add_argument('--all', action='store_true')
    listing.add_argument('--include-legacy', action='store_true')
    for name in ('show', 'read-batch', 'assignment-status'):
        commands.add_parser(name).add_argument('task')
    request = commands.add_parser('request-status')
    request.add_argument('task')
    request.add_argument('--issue', required=True, type=int)
    for name in ('assign', 'release-assignment'):
        command = commands.add_parser(name)
        command.add_argument('task')
        command.add_argument('--person', choices=PEOPLE, required=True)
        command.add_argument('--github-author', required=True)
        if name == 'assign':
            command.add_argument('--issue', required=True, type=int)
        else:
            command.add_argument('--coordinator', action='store_true')
            command.add_argument('--request-issue', type=int)
            command.add_argument('--assignment-issue', type=int)
    claim = commands.add_parser('claim')
    claim.add_argument('task')
    claim.add_argument('--person', choices=PEOPLE, required=True)
    report = commands.add_parser('report')
    report.add_argument('task')
    report.add_argument('--person', choices=PEOPLE, required=True)
    report.add_argument('--status', choices=('in_progress','blocked','completed'), required=True)
    report.add_argument('--note', required=True)
    for name in ('unique-snapshot', 'publication-snapshot', 'snapshot'):
        commands.add_parser(name).add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    manager = Manager(args.hub)
    try:
        if args.command == 'list':
            result = manager.listing(args.person, args.limit, args.offset, args.all, args.available,
                                     args.category, args.include_legacy)
        elif args.command == 'show':
            result = manager.show(args.task)
        elif args.command == 'read-batch':
            result = manager.read_batch(args.task)
        elif args.command == 'assignment-status':
            result = manager.assignment_status(args.task)
        elif args.command == 'request-status':
            result = manager.request_status(args.task, args.issue)
        elif args.command == 'assign':
            result = manager.assign(args.task, args.person, args.issue, args.github_author)
        elif args.command == 'release-assignment':
            result = manager.release_assignment(args.task, args.person, args.github_author, args.coordinator,
                                                 args.request_issue, args.assignment_issue)
        elif args.command == 'claim':
            result = manager.claim(args.task, args.person)
        elif args.command == 'report':
            result = manager.report(args.task, args.person, args.status, args.note)
        else:
            if args.command == 'publication-snapshot':
                result = manager.publication_snapshot()
            elif args.command == 'unique-snapshot':
                result = manager.unique_snapshot()
            else:
                result = manager.legacy.snapshot()
            write(args.output, result)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()

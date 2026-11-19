"""Private immutable batch scopes and legacy fences for GitHub assignments.

This module never creates the old queue's missing mutable directories. GitHub
owns reservations; these existing nonempty fences stop older clients starting
overlapping leaf tasks. Existing workers keep their original report interface.
"""
import hashlib
import json
import os

from coordination.task_manager import digest, require, write
from coordination.unique_queue import (
    MAX_MANIFEST_BYTES, UniqueQueue, _SnapshotLegacyDefinitions, batch_data,
    file_bytes, manifest_rows, parse, pinned_batch_bytes, safe_path, sha,
)


class PrivateCatalogue:
    def __init__(self, root, legacy, generation):
        self.root = safe_path(root)
        self.legacy = legacy
        self.generation = generation
        self.owner = self.root.stat().st_uid
        require(not self.root.stat().st_mode & 0o022, 'Unprotected immutable queue')
        self.manifest_path = self.root / 'package/manifest.json'
        raw = file_bytes(self.manifest_path, MAX_MANIFEST_BYTES, self.owner)
        require(sha(raw) == generation, 'Wrong immutable queue generation')
        self.rows = {row['id']: row for row in manifest_rows(parse(raw))}
        self.queue = UniqueQueue(self.root, legacy)
        self.config = dict(manifest_sha256=generation)

    def row(self, batch_id):
        require(batch_id in self.rows, 'Unknown immutable batch')
        self.check_generation()
        return self.rows[batch_id]

    def check_generation(self):
        require(sha(file_bytes(self.manifest_path, MAX_MANIFEST_BYTES, self.owner)) == self.generation,
                'Immutable queue generation changed')

    def read_batch(self, batch_id):
        return self.read_row(self.row(batch_id))

    def read_row(self, row):
        raw = pinned_batch_bytes(self.root / 'package' / row['file']['path'], row['file'], self.owner)
        return batch_data(raw, row)

    def tasks(self, batch_id, definitions=None):
        return self.queue.legacy_tasks(self.read_batch(batch_id), definitions)

    def _guard_tasks(self, tasks, plans=None):
        states = []
        for task in tasks.values():
            if not self.queue.valid_fence(task, self.config):
                return dict(schema='kuina-assignment-guard-v1', state='unknown', proof_sha256=None)
            worker = self.legacy.work_claim_record(task)
            reservation = self.legacy.reservation(task)
            status, _ = self.legacy.state(task, plans)
            if worker:
                state = 'working'
            elif reservation and reservation['current']:
                state = 'blocked'
            elif status == 'available':
                state = 'clear'
            else:
                state = 'blocked'
            states.append(dict(id=task['id'], definition_sha256=digest(task), state=state))
        if any(s['state'] == 'working' for s in states):
            overall = 'working'
        elif any(s['state'] == 'blocked' for s in states):
            overall = 'blocked'
        else:
            overall = 'clear'
        proof = json.dumps(dict(generation=self.generation, states=states), sort_keys=True).encode()
        return dict(schema='kuina-assignment-guard-v1', state=overall,
                    proof_sha256=hashlib.sha256(proof).hexdigest())

    def unique_freeze(self, create=False):
        """Old APIs must stay unable to start while GitHub owns reservations."""
        parents = [safe_path(self.root / name) for name in ('claims', 'assignments', 'locks')]
        present = [path.exists() for path in parents]
        if not any(present):
            return True  # Old APIs require these parents; never recreate them.
        if not all(present):
            return False
        self.queue.shared('claims')
        locks = self.queue.shared('locks')
        path = locks / 'global'
        expected = dict(schema='kuina-github-authority-freeze-v1', generation=self.generation,
                        queue_root=str(self.root), coordinator_uid=self.owner)
        if create:
            # A held or uncertain old operation must be reconciled, never stolen.
            path.mkdir(mode=0o755)
            os.chmod(path, 0o755)
            write(path / 'github-authority.json', expected)
        if not path.exists():
            return False
        require(path.stat().st_uid == self.owner and not path.stat().st_mode & 0o022,
                'Unprotected old queue freeze')
        require({entry.name for entry in path.iterdir()} == {'github-authority.json'},
                'Old queue operation is pending or unknown')
        require(parse(file_bytes(path / 'github-authority.json', 4096, self.owner)) == expected,
                'Wrong old queue freeze generation')
        return True

    def unique_state(self, row):
        claim = safe_path(self.root / 'claims' / row['id'])
        if claim.exists():
            require(self.queue.owner(row['id'], row['file']['sha256']) is not None,
                    'Unknown existing unique worker')
            return 'working'
        path = safe_path(self.root / 'assignments' / (row['id'] + '.json'))
        if path.exists():
            record = self.queue.reservation(row)
            if record['current'] is not None:
                return 'blocked'
        return 'clear' if self.unique_freeze() else 'unknown'

    def guard(self, batch_id, action, assignment, proof_sha256=None):
        require(action in ('assign', 'release', 'working'), 'Unknown guard action')
        unique = self.unique_state(self.row(batch_id))
        if unique != 'clear':
            return dict(schema='kuina-assignment-guard-v1', state=unique, proof_sha256=None)
        result = self._guard_tasks(self.tasks(batch_id))
        if action == 'working':
            from coordination.github_work import WorkProtocol
            require(result['state'] == 'clear' and type(assignment) is dict and
                    assignment['batch_id'] == batch_id, 'Working reservation and clear scope required')
            WorkProtocol(self).verify(batch_id, assignment['person'], assignment['assignment_issue'], proof_sha256)
            result['proof_sha256'] = proof_sha256
        else:
            require(proof_sha256 is None, 'Unexpected work preparation for reservation action')
        return result

    def catalogue(self, batch_id):
        row = self.row(batch_id)
        guard = self.guard(batch_id, 'assign', None)
        return dict(schema='kuina-assignment-catalogue-v1', batch_id=batch_id,
                    generation=self.generation, definition_sha256=row['file']['sha256'],
                    assignment_enabled=guard['state'] == 'clear')

    def fence_legacy_starts(self):
        """Explicit migration operation; unknown locks are never removed/retried."""
        require(os.getuid() == self.owner == self.legacy.root.stat().st_uid,
                'Coordinator UID required for migration fences')
        self.check_generation()
        require(self.unique_freeze(create=True), 'Old unique namespace needs manual reconciliation')
        definitions = _SnapshotLegacyDefinitions(self.legacy)
        tasks = {}
        for row in self.rows.values():
            for task_id, task in self.queue.legacy_tasks(self.read_row(row), definitions).items():
                require(task_id not in tasks or digest(tasks[task_id]) == digest(task),
                        'Legacy definition changed across batches')
                tasks[task_id] = task
        for task_id in sorted(tasks):
            self.queue.fence(tasks[task_id], self.config)
        definitions.verify()
        self.check_generation()
        require(all(self.queue.valid_fence(task, self.config) for task in tasks.values()),
                'Migration fences incomplete')
        return dict(schema='kuina-github-legacy-fences-v1', generation=self.generation,
                    fenced_tasks=len(tasks), existing_claims_modified=False)

    def public_catalogue(self):
        """Export only approved batch counts, IDs, hashes and availability."""
        self.check_generation()
        definitions = _SnapshotLegacyDefinitions(self.legacy)
        guards = {}
        batches = []
        for batch_id, row in self.rows.items():
            tasks = self.queue.legacy_tasks(self.read_row(row), definitions)
            for task_id, task in tasks.items():
                if task_id not in guards:
                    guards[task_id] = self._guard_tasks({task_id: task}, definitions.plans)
            enabled = (self.unique_state(row) == 'clear' and
                       all(guards[task_id]['state'] == 'clear' for task_id in tasks))
            batches.append(dict(id=batch_id, category=row['category'],
                                target_count=row['target_count'], series_count=row['series_count'],
                                definition_sha256=row['file']['sha256'], assignment_enabled=enabled))
        definitions.verify()
        self.check_generation()
        return dict(schema='kuina-public-assignment-catalogue-v1', generation=self.generation,
                    batches=batches)

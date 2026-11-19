"""Load the pinned public catalogue and wire the existing private broker route."""
import json
from pathlib import Path

from coordination.github_assignments import digest
from coordination.github_assignments_v2 import Assignments
from coordination.github_backend import AuthorityBackend
from coordination.task_manager import IDS, identifier, require
from coordination.unique_queue import file_bytes, safe_path, sha


class PublicCatalogue:
    def __init__(self, path, expected_sha256):
        self.path = safe_path(Path(path).absolute())
        require(digest(expected_sha256), 'Pinned public catalogue SHA256 required')
        self.expected_sha256 = expected_sha256
        raw = self.read()
        value = json.loads(raw)
        require(type(value) is dict and set(value) in (
            {'schema', 'generation', 'batches'},
            {'schema', 'generation', 'batches', 'legacy_definitions'}), 'Unexpected catalogue fields')
        require(value['schema'] == 'kuina-public-assignment-catalogue-v1' and digest(value['generation']),
                'Unknown public catalogue generation')
        require(type(value['batches']) is list and len(value['batches']) <= 20000, 'Invalid batch count')
        self.generation = value['generation']
        self.rows = {}
        for row in value['batches']:
            require(type(row) is dict and set(row) == {'id', 'category', 'target_count', 'series_count',
                                                      'definition_sha256', 'assignment_enabled'},
                    'Unexpected public batch fields')
            identifier(row['id'])
            require(row['id'] not in self.rows and row['category'] in IDS and
                    type(row['target_count']) is int and 0 < row['target_count'] <= 100 and
                    type(row['series_count']) is int and row['target_count'] <= row['series_count'] <= 9007199254740991 and
                    digest(row['definition_sha256']) and type(row['assignment_enabled']) is bool,
                    'Invalid public batch definition')
            self.rows[row['id']] = dict(row)
        legacy = value.get('legacy_definitions', [])
        require(type(legacy) is list and len(legacy) <= 20000, 'Invalid legacy definition count')
        for row in legacy:
            require(type(row) is dict and set(row) == {'batch_id', 'definition_sha256'},
                    'Unexpected legacy definition fields')
            identifier(row['batch_id'])
            require(row['batch_id'] not in self.rows and digest(row['definition_sha256']),
                    'Invalid or repeated legacy definition')
            self.rows[row['batch_id']] = dict(id=row['batch_id'], definition_sha256=row['definition_sha256'],
                                             assignment_enabled=False)

    def read(self):
        raw = file_bytes(self.path, 8 * 1024 * 1024)
        require(sha(raw) == self.expected_sha256, 'Pinned public catalogue changed')
        return raw

    def __call__(self, batch_id):
        self.read()
        require(batch_id in self.rows, 'Unknown public batch')
        row = self.rows[batch_id]
        return dict(schema='kuina-assignment-catalogue-v1', batch_id=batch_id, generation=self.generation,
                    definition_sha256=row['definition_sha256'], assignment_enabled=row['assignment_enabled'])


def make_backend(config, github, native):
    authority = config.get('assignment_authority', 'native')
    if authority == 'native':
        return native
    require(authority == 'github', 'Unknown assignment authority')
    catalogue = PublicCatalogue(config['assignment_catalogue'], config['assignment_catalogue_sha256'])

    def guard(batch_id, action, assignment, proof_sha256=None):
        arguments = ['github-guard', batch_id, '--action', action]
        if assignment is not None:
            arguments.extend(['--assignment', json.dumps(assignment, separators=(',', ':'))])
        if proof_sha256 is not None:
            arguments.extend(['--proof-sha256', proof_sha256])
        return native.command(*arguments)

    store = Assignments(github, catalogue, guard, path=config.get('assignment_ledger', 'coordination/assignments.json'),
                        branch=config.get('assignment_branch', 'main'))
    return AuthorityBackend(store, native)

"""Read-only, closed metadata migration from a fenced Native Hub.

The coordinator fences first. This exporter never creates a directory, changes a
claim, writes GitHub, or interprets private report text as public metadata.
"""
import copy
import gzip
import json

from coordination.github_assignments import record, receipt, stamp, validate_ledger, SCHEMA
from coordination.task_manager import Hub, digest, identifier, require
from coordination.unique_queue import (
    _SnapshotLegacyDefinitions, closed, file_bytes, file_stamp, parse, safe_path, sha,
)
from unique_dashboard import PEOPLE, TASK_SCHEMA, validate as validate_summary

MAX_BYTES = 8 * 1024 * 1024
MAX_GZIP_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class _Epoch:
    """One export's content facts and strict live directory/file epoch."""
    def __init__(self):
        self.stamps = {}
        self.facts = {}

    def watch(self, path):
        path = safe_path(path)
        if path not in self.stamps:
            self.stamps[path] = file_stamp(path) if path.exists() else None
        return path

    def read(self, path, owner=None, maximum=MAX_METADATA_BYTES):
        path = self.watch(path)
        raw = file_bytes(path, maximum, owner)
        require(file_stamp(path) == self.stamps[path], 'Migration metadata changed during read')
        self.facts[path] = sha(raw)
        return raw

    def directory(self, path):
        path = self.watch(path)
        require(path.is_dir(), 'Required migration directory absent')
        entries = sorted(path.iterdir())
        for entry in entries:
            self.watch(entry)
        return entries

    def verify(self):
        for path in sorted(self.stamps, key=lambda p: len(p.parts), reverse=True):
            actual = file_stamp(path) if safe_path(path).exists() else None
            require(actual == self.stamps[path], 'Migration live metadata epoch changed')

    def fingerprint(self, roots, definitions):
        # Paths/UIDs and report bodies remain private. Only this digest leaves.
        def label(path):
            for name, root in roots:
                if path == root or root in path.parents:
                    return name + '/' + str(path.relative_to(root))
            raise ValueError('Metadata fact outside the migration roots')
        facts = [dict(key=label(path), stamp=stamp, sha256=self.facts.get(path))
                 for path, stamp in self.stamps.items()]
        facts.sort(key=lambda x: x['key'])
        return sha(packed(dict(files=facts, definitions=definitions)))


def _unique_clear(catalogue, epoch):
    """Missing old mutable parents stay missing; existing ones must be frozen."""
    require(catalogue.unique_freeze(), 'Old unique API is not safely frozen')
    for name in ('claims', 'assignments', 'locks'):
        path = epoch.watch(catalogue.root / name)
        if not path.exists():
            continue
        for entry in epoch.directory(path):
            if name == 'locks':
                require(entry.name == 'global' and entry.is_dir(), 'Unknown old unique operation')
                children = epoch.directory(entry)
                require([p.name for p in children] == ['github-authority.json'], 'Unknown old unique lock')
                epoch.read(children[0], catalogue.owner)
            elif name == 'claims':
                raise ValueError('An existing unique worker needs explicit reconciliation')
            else:
                # Even released/empty history cannot be silently omitted.
                raise ValueError('An existing unique assignment needs explicit reconciliation')


def _publication(catalogue, epoch):
    raw = epoch.read(catalogue.root / 'publication.json', catalogue.owner, 128 * 1024)
    publication = parse(raw)
    closed(publication, ('schema', 'manifest_sha256', 'summary'))
    require(publication['schema'] == 'kuina-unique-publication-v1' and
            publication['manifest_sha256'] == catalogue.generation,
            'Publication generation does not match the private catalogue')
    summary = publication['summary']
    validate_summary(summary, dict(schema=TASK_SCHEMA, generated_at=summary.get('generated_at'),
                                  people=[dict(id=k, name=v) for k, v in PEOPLE.items()], batches=[]))
    return copy.deepcopy(summary)


def _reservation(task, hub, epoch):
    path = epoch.watch(hub.root / 'assignments' / (task['id'] + '.json'))
    if not path.exists():
        return None, None
    epoch.read(path, hub.root.stat().st_uid)
    value = hub.reservation(task)
    require(value['history'] == [] and value['current'] is not None,
            'Released or historical Native assignments require explicit reconciliation')
    current = value['current']
    requests = value.get('requests')
    expected = dict(task_id=task['id'], request_issue=current['issue'], action='assign',
                    person=current['person'], status='confirmed')
    require(requests == {str(current['issue']): expected},
            'Exactly the original confirmed assignment receipt is required')
    return current, expected


def export(catalogue):
    """Return a bounded public envelope; requires explicit prior migration fences."""
    hub = catalogue.legacy
    require(hub.self_service(), 'Native self-service mode required')
    catalogue.check_generation()
    definitions = _SnapshotLegacyDefinitions(hub)
    epoch = _Epoch()
    epoch.watch(hub.root)
    epoch.watch(catalogue.root)
    for name in ('claims', 'work-claims', 'task-locks'):
        hub.shared_directory(name)
    for name in ('assignments', 'verified'):
        hub.protected(hub.root / name)
    for name in ('self-service.json', '.self-service-migration-lock', '.coordinator-lock'):
        path = epoch.watch(hub.root / name)
        if path.exists():
            require(name == 'self-service.json', 'Native coordination operation pending')
            mode = parse(epoch.read(path, hub.root.stat().st_uid))
            closed(mode, ('schema_version', 'status', 'enabled_at', 'sentinel_ids'))
            require(type(mode['schema_version']) is int and mode['schema_version'] == 1 and
                    mode['status'] == 'enabled' and type(mode['sentinel_ids']) is list,
                    'Current Native self-service mode invalid')
            stamp(mode['enabled_at'])
            for task_id in mode['sentinel_ids']:
                identifier(task_id)
            require(len(set(mode['sentinel_ids'])) == len(mode['sentinel_ids']), 'Duplicate sentinel IDs')
    fresh = Hub(hub.root)
    require(fresh.self_service() and fresh._self_service == hub._self_service,
            'Native cached mode and current sentinel authority differ')
    config = parse(epoch.read(catalogue.root / 'queue.json', catalogue.owner, 4096))
    closed(config, ('schema', 'manifest_sha256', 'legacy_hub', 'installed_at'))
    require(config['schema'] == 'kuina-unique-installed-v1' and
            config['manifest_sha256'] == catalogue.generation and config['legacy_hub'] == str(hub.root),
            'Installed queue and Native Hub binding differ')
    epoch.read(catalogue.manifest_path, catalogue.owner, 8 * 1024 * 1024)
    summary = _publication(catalogue, epoch)
    _unique_clear(catalogue, epoch)

    # Resolve every manifest reference, then census all actual Native journals,
    # including current reservations not referenced by this queue generation.
    referenced = {}
    for row in catalogue.rows.values():
        referenced.update(catalogue.queue.legacy_tasks(catalogue.read_row(row), definitions))
    candidates = set(referenced)
    for name in ('claims', 'work-claims', 'assignments', 'verified', 'task-locks'):
        for path in epoch.directory(hub.root / name):
            if name == 'assignments' and path.name == '.keep':
                require(epoch.read(path, hub.root.stat().st_uid) == b'', 'Unknown assignment marker')
                continue
            if name in ('assignments', 'verified'):
                require(path.name.endswith('.json') and path.is_file(), 'Unknown Native metadata entry')
                task_id = path.stem
            else:
                require(path.is_dir(), 'Unknown Native journal entry')
                task_id = path.name
                for child in epoch.directory(path):
                    allowed = (child.name == 'unique-fence.json' if name == 'task-locks' else
                               child.name == 'owner.json' or
                               child.name.startswith('report-') and child.name.endswith('.json'))
                    require(allowed and child.is_file(), 'Unknown nested Native journal')
                    epoch.read(child, path.stat().st_uid)
            identifier(task_id)
            candidates.add(task_id)

    records, receipts, legacy_definitions = [], [], []
    workers = reservations = sentinels = parents = 0
    for task_id in sorted(candidates):
        task, task_hash = definitions.resolve(task_id)
        if task_id in definitions.plans:
            # Original parent reservation is already validated by batch_plans.
            # It is not a collection worker and cannot acquire a GH child row.
            require(not (hub.root / 'assignments' / (task_id + '.json')).exists() and
                    not (hub.root / 'work-claims' / task_id).exists() and
                    not (hub.root / 'task-locks' / task_id).exists(),
                    'Unexpected mutable parent assignment or operation')
            parents += 1
            continue
        current, _ = _reservation(task, hub, epoch)
        worker = hub.work_claim_record(task)
        status, updated_at = hub.state(task, definitions.plans)
        if task_id in referenced or worker or current or (hub.root / 'task-locks' / task_id).exists():
            require(catalogue.queue.valid_fence(task, catalogue.config), 'Legacy start fence missing or unknown')
        if task_id in hub._self_service:
            sentinels += 1
        if not worker and current is None:
            continue
        require(status in ('assigned', 'active', 'blocked', 'awaiting_verification', 'verified'),
                'Current Native state cannot be imported')
        person = worker[1]['person'] if worker else current['person']
        require(current is None or current['person'] == person, 'Worker and reservation participants disagree')
        created_at = worker[1]['claimed_at'] if worker else current['assigned_at']
        if current:
            reservations += 1
            item = dict(request_issue=current['issue'], batch_id=task_id, action='assign', person=person,
                        author=current['github_author'].casefold(), assignment_issue=None, proof_sha256=None,
                        status='confirmed', recorded_at=current['assigned_at'], definition_sha256=task_hash,
                        catalogue_generation=catalogue.generation, origin='migration')
            receipt(item)
            receipts.append(item)
        proof = None
        if worker:
            workers += 1
            path = worker[0] / 'owner.json'
            proof = sha(epoch.read(path, worker[1]['uid']))
        item = dict(batch_id=task_id, person=person, author=current['github_author'].casefold() if current else None,
                    assignment_issue=current['issue'] if current else None, status=status,
                    definition_sha256=task_hash, catalogue_generation=catalogue.generation,
                    created_at=created_at, updated_at=updated_at, origin='migration',
                    work_proof_sha256=proof, working_request_issue=None)
        record(item)
        records.append(item)
        legacy_definitions.append(dict(batch_id=task_id, definition_sha256=task_hash))

    require(len({r['request_issue'] for r in receipts}) == len(receipts), 'Native issue reused across reservations')
    public = catalogue.public_catalogue()
    closed(public, ('schema', 'generation', 'batches'))
    require(public['schema'] == 'kuina-public-assignment-catalogue-v1' and
            public['generation'] == catalogue.generation and type(public['batches']) is list and
            len(public['batches']) == len(catalogue.rows), 'Public catalogue coverage differs')
    seen = set()
    for row in public['batches']:
        closed(row, ('id', 'category', 'target_count', 'series_count', 'definition_sha256', 'assignment_enabled'))
        require(row['id'] in catalogue.rows and row['id'] not in seen, 'Unexpected public batch')
        expected = catalogue.rows[row['id']]
        require(all(row[k] == expected[k] for k in ('id', 'category', 'target_count', 'series_count')) and
                row['definition_sha256'] == expected['file']['sha256'] and
                type(row['assignment_enabled']) is bool, 'Public batch binding differs')
        seen.add(row['id'])
    public['legacy_definitions'] = legacy_definitions
    for path in definitions.stamps:
        epoch.watch(path)
        if path.is_file():
            epoch.read(path, path.stat().st_uid)
    definitions.verify()
    _unique_clear(catalogue, epoch)
    catalogue.check_generation()
    epoch.verify()
    source_sha = epoch.fingerprint([('hub', hub.root), ('queue', catalogue.root)],
                                   {key: value[1] for key, value in sorted(definitions.tasks.items())})
    migration = dict(schema='kuina-assignment-migration-v1', complete=True, source_sha256=source_sha,
                     catalogue_generation=catalogue.generation, records=records, receipts=receipts)
    validate_ledger(dict(schema=SCHEMA, migration={k: migration[k] for k in
                    ('complete', 'source_sha256', 'catalogue_generation')},
                    assignments={r['batch_id']: r for r in records},
                    receipts={str(r['request_issue']): r for r in receipts}))
    result = dict(schema='kuina-github-migration-export-v1', catalogue=public, migration=migration, summary=summary,
                  provenance=dict(source_sha256=source_sha, referenced_legacy_tasks=len(referenced),
                                  actual_workers=workers, reservations=reservations, original_receipts=len(receipts),
                                  sentinels_ignored=sentinels, parents_ignored=parents,
                                  metadata_files_hashed=len(epoch.facts)))
    encode(result)
    return result


def encode(value, max_bytes=MAX_BYTES, max_compressed_bytes=MAX_GZIP_BYTES):
    """Serialize metadata only; callers own any explicit file/transport operation."""
    raw = packed(value)
    require(len(raw) <= min(max_bytes, MAX_BYTES), 'Migration export exceeds JSON bound')
    compressed = gzip.compress(raw, mtime=0)
    require(len(compressed) <= min(max_compressed_bytes, MAX_GZIP_BYTES), 'Migration export exceeds gzip bound')
    return raw, compressed

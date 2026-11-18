"""Private, additive unique repair queue. Never publishes or certifies data.

Manifest (closed): {schema: kuina-unique-queue-v1, batches: [
  {id, category, target_count, series_count, file: {path, bytes, sha256}}]}.
Batch (closed): {schema: kuina-unique-batch-v1, id, targets: [
  {target_id, legacy_tasks: [{id, task_sha256}], series_ids: [original IDs]}]}.

Install once into a fresh canonical root. Inputs contain metadata only; callers
must review scientific identities separately. Up to 100 targets per batch;
there is no numeric-field cap within the 8 MiB batch-file bound. All original
series IDs and target IDs must be unique across the installed package.

Legacy task-lock fences persist permanently and block old v3 starts while
allowing old reports. Unknown locks are never stolen. Existing real legacy
work or reservations, including the same person's, must continue via legacy.
Claims and journals never expire. Interrupted mkdir/write operations require
manual reconciliation; actual worker claims are never retried, repaired, released
or verified. Coordinator-only GitHub reservations have durable request receipts
and can be released by their origin author before an actual worker claim.
Unix UID is the worker identity; roster names are declarations as in old Hub.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from coordination.task_manager import Hub, IDS, PEOPLE, digest, identifier, instant, now, require, write

MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}')


def closed(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields), 'closed metadata schema required')


def safe_path(path):
    path = Path(path).absolute()
    require(not any(part.is_symlink() for part in (path, *path.parents)), 'symlink path unsupported')
    require(path.resolve() == path, 'canonical path required')
    return path


def file_bytes(path, maximum, owner=None):
    path = safe_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, 'metadata file bound/type invalid')
        if owner is not None:
            require(before.st_uid == owner and not before.st_mode & 0o022, 'metadata ownership/mode invalid')
        # NFS pathname attributes may be stale before open. The held descriptor
        # is authoritative; the final lexical path must still name that file.
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(before.st_size + 1)
            after = os.fstat(descriptor)
        final = path.lstat()
        def signature(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(raw) != before.st_size or signature(before) != signature(after) or signature(after) != signature(final):
            detail = dict(schema='kuina-metadata-read-failure-v1', path=str(path)[:512],
                          raw_length=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                          fd_before=signature(before), fd_after=signature(after), path_after=signature(final))
            raise ValueError('metadata changed during read: ' + json.dumps(detail, sort_keys=True, separators=(',', ':')))
        return raw
    finally:
        os.close(descriptor)


def pinned_batch_bytes(path, pin, owner=None):
    """Read a batch with an exact content pin from its validated manifest.

    ctime alone can change as NFS attributes refresh. It cannot authorize new
    payloads: every returned byte must match the manifest hash and byte count.
    Live coordination records continue to use strict file_bytes instead.
    """
    closed(pin, ('path', 'bytes', 'sha256'))
    require(type(pin['bytes']) is int and 0 < pin['bytes'] <= MAX_BATCH_BYTES and
            isinstance(pin['sha256'], str) and SHA.fullmatch(pin['sha256']), 'invalid immutable batch pin')
    path = safe_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and not before.st_mode & 0o022 and
                (owner is None or before.st_uid == owner), 'immutable batch ownership/mode/type invalid')
        require(before.st_size == pin['bytes'], 'batch file hash/size mismatch')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(pin['bytes'] + 1)
            after = os.fstat(descriptor)
        final = path.lstat()
        def signature(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                    info.st_size, info.st_mtime_ns)
        require(signature(before) == signature(after) == signature(final), 'immutable batch changed during read')
        require(len(raw) == pin['bytes'] and hashlib.sha256(raw).hexdigest() == pin['sha256'],
                'batch file hash/size mismatch')
        return raw
    finally:
        os.close(descriptor)


def parse(raw):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique_keys)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_stamp(path):
    info = safe_path(path).stat()
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def count(value):
    require(type(value) is int and 0 < value <= 9007199254740991, 'positive count required')


def manifest_rows(data):
    closed(data, ('schema', 'batches'))
    require(data['schema'] == 'kuina-unique-queue-v1' and isinstance(data['batches'], list) and
            data['batches'], 'invalid queue manifest')
    ids, paths = set(), set()
    for row in data['batches']:
        closed(row, ('id', 'category', 'target_count', 'series_count', 'file'))
        identifier(row['id'])
        require(row['id'] not in ids and row['category'] in IDS, 'duplicate batch or invalid category')
        ids.add(row['id'])
        count(row['target_count'])
        count(row['series_count'])
        require(row['target_count'] <= 100, 'batch target limit exceeded')
        pin = row['file']
        closed(pin, ('path', 'bytes', 'sha256'))
        relative = pin['path']
        require(isinstance(relative, str) and relative.endswith('.json') and '\\' not in relative and
                not relative.startswith('/') and all(p not in ('', '.', '..') for p in relative.split('/')),
                'unsafe batch path')
        require(relative not in paths and relative != 'manifest.json', 'duplicate/reserved batch path')
        paths.add(relative)
        require(type(pin['bytes']) is int and 0 < pin['bytes'] <= MAX_BATCH_BYTES and
                isinstance(pin['sha256'], str) and SHA.fullmatch(pin['sha256']), 'invalid batch file pin')
    return data['batches']


def batch_data(raw, row):
    pin = row['file']
    require(len(raw) == pin['bytes'] and sha(raw) == pin['sha256'], 'batch file hash/size mismatch')
    data = parse(raw)
    closed(data, ('schema', 'id', 'targets'))
    require(data['schema'] == 'kuina-unique-batch-v1' and data['id'] == row['id'] and
            isinstance(data['targets'], list) and len(data['targets']) == row['target_count'], 'batch target coverage mismatch')
    series_count = 0
    for target in data['targets']:
        closed(target, ('target_id', 'legacy_tasks', 'series_ids'))
        identifier(target['target_id'])
        require(isinstance(target['legacy_tasks'], list) and target['legacy_tasks'], 'legacy task membership required')
        tasks = set()
        for task in target['legacy_tasks']:
            closed(task, ('id', 'task_sha256'))
            identifier(task['id'])
            require(task['id'] not in tasks and isinstance(task['task_sha256'], str) and
                    SHA.fullmatch(task['task_sha256']), 'invalid legacy task pin')
            tasks.add(task['id'])
        require(isinstance(target['series_ids'], list) and target['series_ids'] and
                all(isinstance(value, str) and 0 < len(value) <= 256 for value in target['series_ids']),
                'invalid original series IDs')
        series_count += len(target['series_ids'])
    require(series_count == row['series_count'], 'batch series count mismatch')
    return data


class _SnapshotLegacyDefinitions:
    """One read-only scan's immutable definitions, never live worker state.

    The existing Hub validates the plan index and original parent reservations.
    Protected definitions/index paths are stamped before loading and rechecked
    at completion. Each command gets a new resolver; claim/assign paths do not
    use it and retain their fresh checks under the existing mutex.
    """
    def __init__(self, legacy):
        self.legacy = legacy
        self.stamps = {}
        self.tasks = {}
        self.watch(legacy.root/'tasks')
        directory = self.watch(legacy.root/'batch-plans')
        if directory.exists():
            for folder in directory.iterdir():
                require(folder.is_dir() and not folder.name.startswith('.'),
                        'unexpected batch plan; reconcile manually')
                parent_id = identifier(folder.name)
                for path in (folder, folder/'plan.json', folder/'tasks',
                             legacy.root/'tasks'/(parent_id+'.json'),
                             legacy.root/'claims'/parent_id,
                             legacy.root/'claims'/parent_id/'owner.json'):
                    self.watch(path)
        self.plans = legacy.batch_plans()
        self.verify()

    def watch(self, path):
        path = safe_path(path)
        if path not in self.stamps:
            self.stamps[path] = file_stamp(path) if path.exists() else None
        return path

    def verify(self):
        for path, expected in self.stamps.items():
            actual = file_stamp(path) if safe_path(path).exists() else None
            require(actual == expected, 'legacy definition/index metadata changed during snapshot')

    def resolve(self, task_id):
        identifier(task_id)
        if task_id not in self.tasks:
            path = self.watch(self.legacy.root/'tasks'/(task_id+'.json'))
            if not path.exists():
                matches = [parent for parent, plan in self.plans.items()
                           if task_id.startswith(plan['child_prefix'])]
                require(len(matches) == 1, 'unknown or ambiguous legacy task ID')
                path = self.watch(self.legacy.root/'batch-plans'/matches[0]/'tasks'/(task_id+'.json'))
            task = self.legacy._read_task(path)
            require(file_stamp(path) == self.stamps[path], 'legacy definition changed during read')
            self.tasks[task_id] = task, digest(task)
        return self.tasks[task_id]


class UniqueQueue:
    def __init__(self, root, legacy_hub):
        self.root = safe_path(root)
        self.legacy = legacy_hub
        self._uncertain = False

    def install(self, manifest_path):
        """Coordinator-only, fresh installation. No legacy locks or records touched."""
        source = safe_path(manifest_path)
        raw = file_bytes(source, MAX_MANIFEST_BYTES)
        rows = manifest_rows(parse(raw))
        require(not self.root.exists(), 'queue already exists; never overwrite')
        require(self.legacy.self_service(), 'legacy self-service mode required')
        require(self.legacy.root.stat().st_uid == os.getuid(), 'legacy coordinator owner required')
        targets, series, pins = set(), set(), {}
        # Validate globally before creating any queue state; read again while copying.
        for row in rows:
            data = batch_data(pinned_batch_bytes(source.parent/row['file']['path'], row['file'], os.getuid()), row)
            for target in data['targets']:
                require(target['target_id'] not in targets, 'duplicate canonical target across batches')
                targets.add(target['target_id'])
                for value in target['series_ids']:
                    require(value not in series, 'duplicate original series across targets')
                    series.add(value)
                for task in target['legacy_tasks']:
                    require(task['id'] not in pins or pins[task['id']] == task['task_sha256'], 'inconsistent legacy task hash')
                    pins[task['id']] = task['task_sha256']
        self.root.mkdir(mode=0o755)
        os.chmod(self.root, 0o755)
        package = self.root/'package'
        package.mkdir(mode=0o755)
        os.chmod(package, 0o755)
        for row in rows:
            body = pinned_batch_bytes(source.parent/row['file']['path'], row['file'], os.getuid())
            batch_data(body, row)
            destination = package/row['file']['path']
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            for directory in destination.parents:
                os.chmod(directory, 0o755)
                if directory == package:
                    break
            with destination.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o444)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        with (package/'manifest.json').open('xb') as stream:
            os.fchmod(stream.fileno(), 0o444)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        (self.root/'assignments').mkdir(mode=0o755)
        os.chmod(self.root/'assignments', 0o755)
        for name in ('claims', 'locks'):
            (self.root/name).mkdir(mode=0o1777)
            os.chmod(self.root/name, 0o1777)
        # Commit last. Partial installs have no config and fail closed.
        write(self.root/'queue.json', dict(schema='kuina-unique-installed-v1', manifest_sha256=sha(raw),
                                          legacy_hub=str(safe_path(self.legacy.root)), installed_at=now()))
        return dict(batches=len(rows), targets=len(targets), series=len(series), manifest_sha256=sha(raw))

    def configuration(self):
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'queue root ownership/mode invalid')
        config = parse(file_bytes(self.root/'queue.json', 4096, info.st_uid))
        closed(config, ('schema', 'manifest_sha256', 'legacy_hub', 'installed_at'))
        require(config['schema'] == 'kuina-unique-installed-v1' and
                config['legacy_hub'] == str(safe_path(self.legacy.root)) and
                isinstance(config['manifest_sha256'], str) and SHA.fullmatch(config['manifest_sha256']), 'queue identity mismatch')
        require(instant(config['installed_at']) <= datetime.now(timezone.utc), 'invalid installation time')
        require(self.legacy.self_service(), 'legacy self-service mode required')
        assignments = safe_path(self.root/'assignments').stat()
        require(stat.S_ISDIR(assignments.st_mode) and assignments.st_uid == info.st_uid and
                stat.S_IMODE(assignments.st_mode) == 0o755, 'invalid protected assignments directory')
        return config, info.st_uid

    def package_row(self, batch_id):
        identifier(batch_id)
        config, owner = self.configuration()
        raw = file_bytes(self.root/'package/manifest.json', MAX_MANIFEST_BYTES, owner)
        require(sha(raw) == config['manifest_sha256'], 'installed manifest hash mismatch')
        rows = manifest_rows(parse(raw))
        matches = [row for row in rows if row['id'] == batch_id]
        require(len(matches) == 1, 'unknown unique batch')
        return matches[0], config, owner

    def read(self, batch_id):
        row, _, owner = self.package_row(batch_id)
        return batch_data(pinned_batch_bytes(self.root/'package'/row['file']['path'], row['file'], owner), row)

    def shared(self, name):
        _, owner = self.configuration()
        path = safe_path(self.root/name)
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == owner and
                stat.S_IMODE(info.st_mode) == 0o1777, 'invalid shared queue directory')
        return path

    @contextmanager
    def mutex(self):
        lock = self.shared('locks')/'global'
        lock.mkdir(mode=0o755)  # Exclusive across processes/users; never wait or steal.
        os.chmod(lock, 0o755)
        self._uncertain = False
        try:
            yield
        except (ValueError, FileExistsError):
            raise
        except BaseException:
            self._uncertain = True
            raise
        finally:
            if not self._uncertain:
                lock.rmdir()

    def owner(self, batch_id, batch_sha):
        path = safe_path(self.shared('claims')/identifier(batch_id))
        if not path.exists():
            return None
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'claim directory ownership invalid')
        owner = parse(file_bytes(path/'owner.json', 4096, info.st_uid))
        closed(owner, ('uid', 'person', 'batch_sha256', 'claimed_at'))
        require(type(owner['uid']) is int and owner['uid'] == info.st_uid and owner['person'] in PEOPLE and
                owner['batch_sha256'] == batch_sha and instant(owner['claimed_at']) <= datetime.now(timezone.utc),
                'unique claim ownership/hash mismatch')
        return path, owner

    def state(self, batch_id, batch_sha):
        claim = self.owner(batch_id, batch_sha)
        if claim is None:
            return 'available', None
        path, owner = claim
        require(not (path/'.report-lock').exists(), 'interrupted report; reconcile manually')
        records = []
        for entry in path.iterdir():
            require(entry.name == 'owner.json' or re.fullmatch(r'report-[0-9a-f]{32}[.]json', entry.name),
                    'unknown claim journal entry; reconcile manually')
            if entry.name == 'owner.json':
                continue
            record = parse(file_bytes(entry, 64 * 1024, owner['uid']))
            closed(record, ('uid', 'person', 'batch_sha256', 'at', 'status', 'note'))
            require(record['uid'] == owner['uid'] and record['person'] == owner['person'] and
                    record['batch_sha256'] == batch_sha and record['status'] in ('active','blocked','awaiting_verification') and
                    isinstance(record['note'], str) and 0 < len(record['note'].strip()) <= 4000 and
                    instant(owner['claimed_at']) <= instant(record['at']) <= datetime.now(timezone.utc), 'invalid private report journal')
            records.append(record)
        records.sort(key=lambda record: instant(record['at']))
        require(not any(record['status'] == 'awaiting_verification' for record in records[:-1]), 'report follows final completion')
        return (records[-1]['status'] if records else 'active'), owner

    def show(self, batch_id):
        """Private effective availability, including fresh legacy ownership."""
        self.require_idle()
        row, config, metadata_owner = self.package_row(batch_id)
        return self._show_row(row, config, metadata_owner)

    def require_idle(self):
        require(not (self.shared('locks')/'global').exists(),
                'queue operation pending or interrupted; reconcile before using availability')

    def snapshot(self):
        """Read one immutable package manifest per scan, never cache worker state.

        The second manifest/config and legacy-definition stamp checks close
        the operation. This is advisory availability; mutations always take their own fresh claim and
        legacy checks under the mutex.
        """
        self.require_idle()
        config, metadata_owner = self.configuration()
        manifest = self.root/'package/manifest.json'
        raw = file_bytes(manifest, MAX_MANIFEST_BYTES, metadata_owner)
        require(sha(raw) == config['manifest_sha256'], 'installed manifest hash mismatch')
        rows = manifest_rows(parse(raw))
        batch_stamps = {self.root/'package'/row['file']['path']:
                        file_stamp(self.root/'package'/row['file']['path']) for row in rows}
        definitions = _SnapshotLegacyDefinitions(self.legacy)
        views = [self._show_row(row, config, metadata_owner, definitions) for row in rows]
        definitions.verify()
        for row in rows:
            path = self.root/'package'/row['file']['path']
            before, after = batch_stamps[path], file_stamp(path)
            require(before[:-1] == after[:-1], 'installed batch metadata changed during snapshot')
            if before[-1] != after[-1]:
                # One extra content verification only when ctime changed.
                pinned_batch_bytes(path, row['file'], metadata_owner)
        require(self.configuration() == (config, metadata_owner), 'queue configuration changed during snapshot')
        require(file_bytes(manifest, MAX_MANIFEST_BYTES, metadata_owner) == raw,
                'installed manifest changed during snapshot')
        self.require_idle()
        return views

    def _show_row(self, row, config, metadata_owner, definitions=None):
        """Internal row view for a validated manifest, with fresh live records."""
        self.require_idle()
        data = batch_data(pinned_batch_bytes(self.root/'package'/row['file']['path'], row['file'], metadata_owner), row)
        status, owner = self.state(row['id'], row['file']['sha256'])
        reservation = self.reservation(row)
        current = reservation['current'] if reservation else None
        tasks = self.legacy_tasks(data, definitions)
        plans = None if definitions is None else definitions.plans
        blockers = []
        for task_id in sorted(tasks):
            task = tasks[task_id]
            fenced = self.valid_fence(task, config)
            require(owner is None and current is None or fenced,
                    'claimed or reserved unique batch missing legacy fence; reconcile manually')
            legacy_state, _ = self.legacy.state(task, plans)
            if legacy_state != 'available':
                blockers.append(dict(task_id=task_id, state=legacy_state,
                                     assignee=self.legacy.effective_assignee(task, plans)))
        require(owner is None or not blockers, 'claimed unique batch conflicts with legacy work; reconcile manually')
        if owner is None and blockers:
            status = 'blocked'
        require(owner is None or current is None or owner['person'] == current['person'], 'claim/reservation owner conflict')
        assignee = current['person'] if current else None
        if owner:
            assignee = owner['person']
        if owner is None and current and not blockers:
            status = 'assigned'
        return dict(row, status=status, assignee=assignee,
                    assignment_issue=current['issue'] if current else None,
                    batch_sha256=row['file']['sha256'], legacy_blockers=blockers)

    def legacy_tasks(self, data, definitions=None):
        tasks, hashes = {}, {}
        for target in data['targets']:
            for pin in target['legacy_tasks']:
                task_id = pin['id']
                if task_id not in tasks:
                    if definitions is None:
                        tasks[task_id] = self.legacy.task(task_id)
                    else:
                        tasks[task_id], hashes[task_id] = definitions.resolve(task_id)
                actual_hash = digest(tasks[task_id]) if definitions is None else hashes[task_id]
                require(actual_hash == pin['task_sha256'], 'legacy task hash mismatch')
        return tasks

    def check_legacy(self, tasks):
        for task in tasks.values():
            require(self.legacy.work_claim_record(task) is None, 'actual work exists; continue legacy task '+task['id'])
            reservation = self.legacy.reservation(task)
            require(reservation is None or reservation['current'] is None,
                    'assignment exists; continue legacy task '+task['id'])
            status, _ = self.legacy.state(task)
            require(status == 'available', 'legacy task unavailable; continue legacy task '+task['id'])

    def fence_identity(self, task, config):
        return dict(schema='kuina-unique-fence-v1', queue_root=str(self.root),
                    manifest_sha256=config['manifest_sha256'], task_id=task['id'], task_sha256=digest(task))

    def valid_fence(self, task, config):
        """Read-only: absence is allowed; unknown or changed locks fail closed."""
        path = safe_path(self.legacy.shared_directory('task-locks')/task['id'])
        if not path.exists():
            return False
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'unknown legacy fence/lock')
        require((path/'unique-fence.json').is_file(), 'unknown legacy fence/lock; reconcile manually')
        expected = self.fence_identity(task, config)
        token = parse(file_bytes(path/'unique-fence.json', 4096, info.st_uid))
        closed(token, (*expected, 'uid'))
        require(token == dict(expected, uid=info.st_uid), 'unknown or forged legacy fence')
        require({entry.name for entry in path.iterdir()} == {'unique-fence.json'}, 'unknown legacy fence contents')
        return True

    def fence(self, task, config):
        path = self.legacy.shared_directory('task-locks')/task['id']
        try:
            path.mkdir(mode=0o755)
        except FileExistsError:
            require(self.valid_fence(task, config), 'legacy lock changed during inspection; reconcile manually')
            return
        try:
            os.chmod(path, 0o755)
            write(path/'unique-fence.json', dict(self.fence_identity(task, config), uid=os.getuid()))
        except BaseException:
            self._uncertain = True
            raise

    def reservation(self, row):
        _, owner = self.configuration()
        path = safe_path(self.root/'assignments'/(row['id']+'.json'))
        if not path.exists():
            return None
        record = parse(file_bytes(path, 16 * 1024 * 1024, owner))
        closed(record, ('batch_sha256', 'current', 'history', 'requests'))
        require(record['batch_sha256'] == row['file']['sha256'] and isinstance(record['history'], list) and
                isinstance(record['requests'], dict), 'assignment hash/record mismatch')
        def entry(value, released=False):
            fields = ('person', 'issue', 'github_author', 'assigned_at')
            closed(value, (*fields, 'released_at', 'released_by') if released else fields)
            require(value['person'] in PEOPLE, 'invalid reservation person')
            count(value['issue'])
            Hub.github_author(value['github_author'])
            require(instant(value['assigned_at']) <= datetime.now(timezone.utc), 'invalid reservation timestamp')
            if released:
                Hub.github_author(value['released_by'])
                require(value['released_by'].lower() == value['github_author'].lower() and
                        instant(value['assigned_at']) <= instant(value['released_at']) <= datetime.now(timezone.utc),
                        'invalid reservation release history')
        if record['current'] is not None:
            entry(record['current'])
        for value in record['history']:
            entry(value, True)
        for issue, receipt in record['requests'].items():
            require(isinstance(issue, str) and issue.isascii() and issue.isdecimal() and
                    str(int(issue)) == issue, 'invalid request receipt key')
            Hub.validate_request_receipt(receipt, row['id'], int(issue))
        return record

    def coordinator(self):
        _, owner = self.configuration()
        require(os.getuid() == owner, 'queue coordinator UID required')

    def request_status(self, batch_id, issue):
        count(issue)
        row, _, _ = self.package_row(batch_id)
        self.read(batch_id)
        record = self.reservation(row)
        return record['requests'].get(str(issue)) if record else None

    def assignment_status(self, batch_id):
        row = self.show(batch_id)
        return dict(task_id=batch_id, status=row['status'], assignee=row['assignee'],
                    assignment_issue=row['assignment_issue'])

    def save_reservation(self, batch_id, record):
        require(len(json.dumps(record).encode()) <= 16 * 1024 * 1024, 'assignment journal byte bound exceeded')
        try:
            write(self.root/'assignments'/(batch_id+'.json'), record)
        except BaseException:
            self._uncertain = True
            raise

    @staticmethod
    def receipt(record, batch_id, issue, action, person):
        record['requests'][str(issue)] = dict(task_id=batch_id, request_issue=issue, action=action,
                                            person=person, status='confirmed' if action == 'assign' else 'released')

    def assign(self, batch_id, person, issue, github_author):
        self.coordinator()
        require(person in PEOPLE, 'unknown participant')
        count(issue)
        Hub.github_author(github_author)
        with self.mutex():
            row, config, _ = self.package_row(batch_id)
            data = self.read(batch_id)
            record = self.reservation(row)
            previous = record['requests'].get(str(issue)) if record else None
            status, owner = self.state(batch_id, row['file']['sha256'])
            current = record['current'] if record else None
            if previous:
                require(previous['action'] == 'assign' and previous['person'] == person, 'request issue already used')
                if owner is None:
                    status = 'assigned' if current else 'available'
                original_issue = current['issue'] if current and current['person'] == person else issue
                return dict(status=status, task_id=batch_id, person=person, issue=original_issue)
            require(owner is None, 'actual unique worker claim exists')
            if current:
                require(current['person'] == person and current['github_author'].lower() == github_author.lower(),
                        'unique batch reserved by another participant or author')
            tasks = self.legacy_tasks(data)
            self.check_legacy(tasks)
            for task_id in sorted(tasks):
                self.fence(tasks[task_id], config)
            self.check_legacy(self.legacy_tasks(data))
            record = record or dict(batch_sha256=row['file']['sha256'], current=None, history=[], requests={})
            if current is None:
                record['current'] = dict(person=person, issue=issue, github_author=github_author, assigned_at=now())
            self.receipt(record, batch_id, issue, 'assign', person)
            self.save_reservation(batch_id, record)
            return dict(status='assigned', task_id=batch_id, person=person, issue=record['current']['issue'])

    def release_assignment(self, batch_id, person, github_author, coordinator=False,
                           request_issue=None, assignment_issue=None):
        self.coordinator()
        require(person in PEOPLE, 'unknown participant')
        Hub.github_author(github_author)
        if request_issue is not None:
            count(request_issue)
            count(assignment_issue)
        else:
            require(assignment_issue is None, 'expected assignment requires request issue')
        with self.mutex():
            row, _, _ = self.package_row(batch_id)
            self.read(batch_id)
            record = self.reservation(row)
            previous = record['requests'].get(str(request_issue)) if record and request_issue is not None else None
            if previous:
                require(previous['action'] == 'release' and previous['person'] == person, 'request issue already used')
                return dict(status='available', task_id=batch_id, person=person, issue=assignment_issue)
            require(self.owner(batch_id, row['file']['sha256']) is None, 'cannot release actual unique worker claim')
            current = record['current'] if record else None
            require(current is not None and current['person'] == person, 'no matching current reservation')
            # The legacy coordinator CLI flag grants no author bypass here.
            require(current['github_author'].lower() == github_author.lower(), 'only origin GitHub author may release')
            require(assignment_issue is None or assignment_issue == current['issue'], 'reservation changed since release request')
            self.check_legacy(self.legacy_tasks(self.read(batch_id)))
            record['history'].append(dict(current, released_at=now(), released_by=github_author))
            record['current'] = None
            if request_issue is not None:
                self.receipt(record, batch_id, request_issue, 'release', person)
            self.save_reservation(batch_id, record)
            return dict(status='available', task_id=batch_id, person=person, issue=current['issue'])

    def claim(self, batch_id, person):
        require(person in PEOPLE, 'unknown participant')
        with self.mutex():
            row, config, _ = self.package_row(batch_id)
            data = self.read(batch_id)
            require(self.owner(batch_id, row['file']['sha256']) is None, 'unique batch already claimed; never repeat')
            reservation = self.reservation(row)
            require(not reservation or not reservation['current'] or reservation['current']['person'] == person,
                    'unique batch assigned to another participant')
            tasks = self.legacy_tasks(data)
            # Reject known work before fencing; reservations can still start normally.
            self.check_legacy(tasks)
            for task_id in sorted(tasks):
                self.fence(tasks[task_id], config)
            # All old-v3 claim/assign starts now lose the mkdir race. Recheck fresh.
            self.check_legacy(self.legacy_tasks(data))
            path = self.shared('claims')/batch_id
            path.mkdir(mode=0o755)
            try:
                os.chmod(path, 0o755)
                owner = dict(uid=os.getuid(), person=person, batch_sha256=row['file']['sha256'], claimed_at=now())
                write(path/'owner.json', owner)
            except BaseException:
                self._uncertain = True
                raise
            return owner

    def report(self, batch_id, person, status, note):
        require(person in PEOPLE and status in ('in_progress','blocked','completed'), 'invalid participant/report status')
        require(isinstance(note, str) and 0 < len(note.strip()) <= 4000, 'note must contain 1–4000 characters')
        with self.mutex():
            row, _, _ = self.package_row(batch_id)
            self.read(batch_id)
            current, owner = self.state(batch_id, row['file']['sha256'])
            require(owner is not None and owner['uid'] == os.getuid() and owner['person'] == person,
                    'only actual claim UID/person may report')
            require(current != 'awaiting_verification', 'completion final pending independent review')
            path = self.shared('claims')/batch_id
            lock = path/'.report-lock'
            lock.mkdir(mode=0o755)
            try:
                record = dict(uid=os.getuid(), person=person, batch_sha256=row['file']['sha256'], at=now(),
                              status={'in_progress':'active','blocked':'blocked','completed':'awaiting_verification'}[status], note=note)
                write(path/('report-'+uuid.uuid4().hex+'.json'), record)
                lock.rmdir()
            except BaseException:
                self._uncertain = True
                raise
            return record

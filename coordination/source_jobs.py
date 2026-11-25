"""Additive, protected source jobs using the existing Native work protocol.

Confirming free access creates a metadata-first job, never data eligibility or a
bulk-download permit. Actual collection retains the private source-admission gate.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import stat

from coordination.github_work import WorkProtocol, encoded, sha
from coordination.task_manager import identifier, instant, now, require
from coordination.unique_queue import closed, file_bytes, parse, safe_path

PREFIX = 'unique-source-'
POINTER = 'source-jobs-current.json'
MAX_BYTES = 512 * 1024
JOB_FIELDS = ('id', 'source_ids', 'provider', 'category', 'confirmed_at',
              'window_start', 'window_end_exclusive', 'kind', 'instructions')
INSTRUCTIONS = """Inspect existing Kuina data and metadata first; reuse equivalent verified histories.
This is a confirmed-free-source job, not a certified instrument or unrestricted collection permit.
Read the provider documentation linked by source_ids in the public source-search log.
Check instrument identity, native cadence <=900 seconds, actual history covering
2024-10-01 inclusive to 2026-10-01 exclusive, and internal gaps under the correct
calendar. Archive filenames alone do not establish coverage. Do not fill gaps.
Use your own approved account and credentials; no paid subscriptions, requester-pays
downloads, account creation by the agent, authentication bypass or rate-limit evasion.
Before downloading observations, follow AGENT_TASKS.md's KUINA_SOURCE_MANAGER
proposal/admission workflow for each exact provider/instrument/venue/feed/currency/
adjustment/window. Supply the matching reviewed preflight and bounded resource
policy. Its shared overlap check must admit the exact collection scope first.
An assignment does not bypass source admission, cproj or scheduler/resource policy.
Use Deigo for CPU and Saion for GPU when needed; never bump other jobs. Provider
metadata checks only on login nodes; actual collection uses the approved environment.
Keep originals unfilled. Store new observations/provenance in the shared Kuina
dataset structure, inspect its README first, and keep raw observations remote.
Report in_progress, blocked or completed through the assignment manager as the
actual claiming UID/person. On completion include private artifact/checksum and
coverage evidence, exact results and omissions. A blocker is not finished work.
Completion means collection reported finished; a new matching audit is still
required before dataset eligibility changes. Never publish private evidence in issues.
"""


def validate_manifest(value):
    closed(value, ('schema', 'base_generation', 'jobs'))
    require(value['schema'] == 'kuina-private-source-jobs-v1' and
            isinstance(value['base_generation'], str) and
            re.fullmatch('[0-9a-f]{64}', value['base_generation']), 'Invalid source-job generation')
    require(type(value['jobs']) is list and len(value['jobs']) <= 100, 'Bounded source jobs required')
    seen, providers, sources = set(), set(), set()
    for job in value['jobs']:
        closed(job, JOB_FIELDS)
        identifier(job['id'])
        require(job['id'].startswith(PREFIX) and job['id'] not in seen, 'Invalid or duplicate source-job ID')
        seen.add(job['id'])
        require(isinstance(job['provider'], str) and 0 < len(job['provider']) <= 128 and
                job['provider'].casefold() not in providers, 'One job per provider prevents overlapping searches')
        providers.add(job['provider'].casefold())
        require(type(job['source_ids']) is list and 0 < len(job['source_ids']) <= 30, 'Source IDs required')
        for source in job['source_ids']:
            require(isinstance(source, str) and re.fullmatch('[a-z0-9-]{1,96}', source) and
                    source not in sources, 'Duplicate or invalid source scope')
            sources.add(source)
        require(job['category'] in ('stocks', 'crypto', 'commodities', 'currencies', 'other-markets'),
                'Unknown source-job category')
        require((job['window_start'], job['window_end_exclusive'], job['kind']) ==
                ('2024-10-01', '2026-10-01', 'preflight_then_collection'), 'Source policy changed')
        require(isinstance(job['instructions'], str) and job['instructions'] == INSTRUCTIONS,
                'Reviewed source-admission instructions required')
        require(instant(job['confirmed_at']) <= instant(now()), 'Invalid confirmation time')
    return value


def public_definition(job):
    return dict(id=job['id'], source_ids=job['source_ids'], confirmed_at=job['confirmed_at'],
                definition_sha256=sha(encoded(job)))


def confirm(sources, source_ids, generation, previous=None):
    import acquisition
    acquisition.validate(sources)
    selected = [r for r in sources['sources'] if r['id'] in source_ids]
    require(len(source_ids) == len(set(source_ids)) == len(selected) and selected,
            'Exact known source IDs required')
    require(len({r['provider'] for r in selected}) == 1 and
            all(r['status'] != 'rejected' for r in selected), 'Confirm one free provider per job')
    value = deepcopy(previous) if previous is not None else dict(
        schema='kuina-private-source-jobs-v1', base_generation=generation, jobs=[])
    validate_manifest(value)
    require(value['base_generation'] == generation, 'Existing source-job generation differs')
    provider = selected[0]['provider']
    category = {'forex': 'currencies', 'indices': 'other-markets'}.get(selected[0]['market'], selected[0]['market'])
    identity = dict(provider=provider, source_ids=sorted(source_ids), generation=generation)
    job = dict(id=PREFIX+sha(encoded(identity))[:24], source_ids=sorted(source_ids), provider=provider,
               category=category, confirmed_at=now(), window_start='2024-10-01',
               window_end_exclusive='2026-10-01', kind='preflight_then_collection', instructions=INSTRUCTIONS)
    value['jobs'].append(job)
    return validate_manifest(value)


def catalogue_rows(manifest):
    validate_manifest(manifest)
    # The legacy assignment contract calls these work-unit counts; these are
    # never added to the reviewed dataset/series inventory or eligibility totals.
    return [dict(id=j['id'], category=j['category'], target_count=1, series_count=1,
                 definition_sha256=sha(encoded(j)), assignment_enabled=True) for j in manifest['jobs']]


class SourceOverlay:
    def __init__(self, base):
        self.base, self.legacy, self.generation = base, base.legacy, base.generation
        self.pointer_path = safe_path(self.legacy.root / POINTER)
        self.owner = self.legacy.root.stat().st_uid
        self.pointer_raw = file_bytes(self.pointer_path, 4096, self.owner)
        pointer = parse(self.pointer_raw)
        closed(pointer, ('schema', 'base_generation', 'manifest_path', 'manifest_sha256'))
        require(pointer['schema'] == 'kuina-source-job-authority-v1' and
                pointer['base_generation'] == self.generation, 'Wrong source-job authority')
        self.source_manifest_path = safe_path(Path(pointer['manifest_path']))
        require(self.legacy.root / 'source-jobs' / 'releases' in self.source_manifest_path.parents,
                'Source jobs must be below the protected release directory')
        for path in self.source_manifest_path.parents:
            entry = path.stat()
            require(stat.S_ISDIR(entry.st_mode) and entry.st_uid == self.owner and not entry.st_mode & 0o022,
                    'Unprotected source-job ancestor')
            if path == self.legacy.root:
                break
        self.source_raw = file_bytes(self.source_manifest_path, MAX_BYTES, self.owner)
        require(sha(self.source_raw) == pointer['manifest_sha256'], 'Source-job manifest pin differs')
        manifest = validate_manifest(parse(self.source_raw))
        require(manifest['base_generation'] == self.generation, 'Source-job manifest generation differs')
        self.jobs = {j['id']: j for j in manifest['jobs']}
        require(not set(self.jobs) & set(base.rows), 'Source job shadows an existing repair')
        self.rows = dict(base.rows)
        self.rows.update({r['id']: dict(r, file=dict(sha256=r['definition_sha256']))
                          for r in catalogue_rows(manifest)})
        self.manifest_path = base.manifest_path
        self.extra_dependencies = [self.pointer_path, self.source_manifest_path]

    def __getattr__(self, name):
        return getattr(self.base, name)

    def check_generation(self):
        self.base.check_generation()
        require(file_bytes(self.pointer_path, 4096, self.owner) == self.pointer_raw and
                file_bytes(self.source_manifest_path, MAX_BYTES, self.owner) == self.source_raw,
                'Source-job authority changed during command; reconcile before continuing')

    def row(self, batch_id):
        self.check_generation()
        return self.rows[batch_id] if batch_id in self.jobs else self.base.row(batch_id)

    def read_batch(self, batch_id):
        self.row(batch_id)
        if batch_id in self.jobs:
            return deepcopy(self.jobs[batch_id])
        return self.base.read_batch(batch_id)

    def guard(self, batch_id, action, assignment, proof_sha256=None):
        if batch_id not in self.jobs:
            return self.base.guard(batch_id, action, assignment, proof_sha256)
        self.row(batch_id)
        require(action in ('assign', 'release', 'working'), 'Unknown source-job action')
        claim = safe_path(self.legacy.shared_directory('work-claims') / batch_id)
        require(not claim.is_symlink(), 'Unsafe source-job claim')
        state = 'working' if claim.exists() else 'clear'
        if action == 'working':
            require(state == 'clear' and type(assignment) is dict and assignment['batch_id'] == batch_id,
                    'Unstarted source-job reservation required')
            WorkProtocol(self).verify(batch_id, assignment['person'], assignment['assignment_issue'], proof_sha256)
        else:
            require(proof_sha256 is None, 'Unexpected source work preparation')
        self.check_generation()
        return dict(schema='kuina-assignment-guard-v1', state=state,
                    proof_sha256=proof_sha256 if action == 'working' else sha(self.source_raw))

    def catalogue(self, batch_id):
        if batch_id not in self.jobs:
            return self.base.catalogue(batch_id)
        row = self.row(batch_id)
        return dict(schema='kuina-assignment-catalogue-v1', batch_id=batch_id, generation=self.generation,
                    definition_sha256=row['file']['sha256'],
                    assignment_enabled=self.guard(batch_id, 'assign', None)['state'] == 'clear')

    def public_catalogue(self):
        self.check_generation()
        value = self.base.public_catalogue()
        value['batches'].extend(catalogue_rows(parse(self.source_raw)))
        self.check_generation()
        return value


def with_source_jobs(base):
    path = base.legacy.root / POINTER
    if path.exists() or path.is_symlink():
        return SourceOverlay(base)
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--source-ids', nargs='+', required=True)
    parser.add_argument('--base-generation', required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--public-out', type=Path, required=True)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous else None
    value = confirm(json.loads(args.sources.read_text()), args.source_ids, args.base_generation, previous)
    for path, data in [(args.out, value), (args.public_out, dict(
            schema='kuina-public-source-job-definitions-v1', jobs=[public_definition(j) for j in value['jobs']]))]:
        with path.open('xb') as stream:
            stream.write(encoded(data))
    print(json.dumps(dict(jobs=len(value['jobs']), manifest_sha256=sha(encoded(value)), data_downloads=0)))


if __name__ == '__main__':
    main()

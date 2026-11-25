"""Render only closed delegation metadata from one observed GitHub ledger."""
import json
from pathlib import Path
import tempfile
from coordination.github_assignments import digest, validate_ledger
from coordination.github_assignments_v2 import Assignments
from coordination.task_manager import require
import unique_dashboard
from recovery import retired_batch


def task_snapshot(summary, catalogue, ledger, generated_at, progress=None):
    validate_ledger(ledger)
    Assignments._validate_started(ledger)
    require(type(catalogue) is dict and set(catalogue) in (
        {'schema', 'generation', 'batches'}, {'schema', 'generation', 'batches', 'legacy_definitions'}),
        'Unexpected public catalogue fields')
    require(catalogue['schema'] == 'kuina-public-assignment-catalogue-v1' and
            digest(catalogue['generation']) and
            ledger['migration']['catalogue_generation'] == catalogue['generation'],
            'GitHub and immutable catalogue generations differ')
    require(type(catalogue['batches']) is list and len(catalogue['batches']) <= 20000,
            'Public batch bound exceeded')
    from coordination.assignment_progress import validated
    advisory = validated(ledger, progress)
    batches = []
    for row in catalogue['batches']:
        if row['id'].startswith('unique-source-'):
            continue  # New acquisition work is separate from the audited repair inventory.
        require(not retired_batch(row['id']), 'Confirmed unrecoverable batch cannot enter the work board')
        require(type(row) is dict and set(row) == {'id', 'category', 'target_count', 'series_count',
                                                  'definition_sha256', 'assignment_enabled'} and
                digest(row['definition_sha256']) and type(row['assignment_enabled']) is bool,
                'Unexpected public batch definition')
        current = ledger['assignments'].get(row['id'])
        status = 'available' if row['assignment_enabled'] else 'blocked'
        blockers = [] if row['assignment_enabled'] else ['legacy_reservation']
        assignee, issue = None, None
        if current is not None:
            require(current['definition_sha256'] == row['definition_sha256'] and
                    current['catalogue_generation'] == catalogue['generation'],
                    'Confirmed assignment definition differs')
            status, assignee, issue = current['status'], current['person'], current['assignment_issue']
            if row['id'] in advisory:
                status = advisory[row['id']]['status']
            if current['origin'] == 'migration' and status == 'assigned':
                status = 'blocked'
        batches.append(dict(id=row['id'], category=row['category'], target_count=row['target_count'],
                            series_count=row['series_count'], status=status, assignee=assignee,
                            assignment_issue=issue, blocker_codes=blockers))
    result = dict(schema=unique_dashboard.TASK_SCHEMA, generated_at=generated_at,
                  people=[dict(id=key, name=name) for key, name in unique_dashboard.PEOPLE.items()],
                  batches=batches)
    unique_dashboard.validate(summary, result)
    return result


def render_assets(summary, catalogue, ledger, generated_at, progress=None):
    tasks = task_snapshot(summary, catalogue, ledger, generated_at, progress=progress)
    with tempfile.TemporaryDirectory(prefix='kuina-public-assignments-') as folder:
        unique_dashboard.build(summary, tasks, Path(folder))
        html = (Path(folder) / 'unique.html').read_bytes()
    def encode(value):
        return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    return {'docs/unique.html': html, 'docs/unique-summary.json': encode(summary),
            'docs/unique-tasks.json': encode(tasks)}

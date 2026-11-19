"""Validated public artifacts for the private publisher; no network or data reads."""
from datetime import datetime
import json
from pathlib import Path
import tempfile

import unique_dashboard

GENERATED = frozenset({
    'docs/unique.html', 'docs/unique-summary.json', 'docs/unique-tasks.json'})


def artifacts(summary, tasks):
    """Return the complete closed publication bundle before writing any live file."""
    unique_dashboard.validate(summary, tasks)
    with tempfile.TemporaryDirectory(prefix='kuina-unique-public-') as folder:
        unique_dashboard.build(summary, tasks, folder)
        html = (Path(folder) / 'unique.html').read_text()
    return {
        'docs/unique.html': html,
        'docs/unique-summary.json': json.dumps(summary, indent=2, allow_nan=False) + '\n',
        'docs/unique-tasks.json': json.dumps(tasks, indent=2, allow_nan=False) + '\n',
    }


def changed(previous_summary, previous_tasks, summary, tasks):
    """Publish real changes and a daily heartbeat; reject stale incoming metadata."""
    unique_dashboard.validate(previous_summary, previous_tasks)
    unique_dashboard.validate(summary, tasks)
    unique_dashboard.require_current_eligibility(previous_summary, summary)
    timestamps = []
    for previous, incoming in ((previous_summary, summary), (previous_tasks, tasks)):
        old = datetime.fromisoformat(previous['generated_at'].replace('Z', '+00:00'))
        new = datetime.fromisoformat(incoming['generated_at'].replace('Z', '+00:00'))
        if new < old:
            raise ValueError('Older unique-work metadata cannot replace newer state')
        timestamps.append((old, new))
    previous_content = {key: value for key, value in previous_tasks.items() if key != 'generated_at'}
    incoming_content = {key: value for key, value in tasks.items() if key != 'generated_at'}
    return (summary != previous_summary or previous_content != incoming_content or
            (timestamps[1][1] - timestamps[1][0]).total_seconds() >= 86400)

"""Publication cannot expand the approved public metadata surface."""
from copy import deepcopy
import json
import unittest

import unique_sync
from test_unique_dashboard import fixtures


class UniqueSyncTests(unittest.TestCase):
    def test_exact_artifacts_contain_only_validated_metadata(self):
        summary, tasks = fixtures()
        artifacts = unique_sync.artifacts(summary, tasks)
        self.assertEqual(set(artifacts), {
            'docs/unique.html', 'docs/unique-summary.json', 'docs/unique-tasks.json'})
        self.assertEqual(json.loads(artifacts['docs/unique-summary.json']), summary)
        self.assertEqual(json.loads(artifacts['docs/unique-tasks.json']), tasks)
        self.assertIn('Unique work.', artifacts['docs/unique.html'])
        contaminated = deepcopy(tasks)
        contaminated['batches'][0]['private_path'] = '/private/source'
        with self.assertRaises(ValueError):
            unique_sync.artifacts(summary, contaminated)

    def test_poll_timestamps_do_not_create_repeated_commits(self):
        summary, tasks = fixtures()
        incoming = dict(tasks, generated_at='2026-11-18T01:15:00Z')
        self.assertFalse(unique_sync.changed(summary, tasks, summary, incoming))
        heartbeat = dict(tasks, generated_at='2026-11-19T01:00:00Z')
        self.assertTrue(unique_sync.changed(summary, tasks, summary, heartbeat))
        reserved = deepcopy(incoming)
        reserved['batches'][0].update(status='assigned', assignee='seann', assignment_issue=9)
        self.assertTrue(unique_sync.changed(summary, tasks, summary, reserved))

    def test_older_summary_or_reservations_never_replace_newer_state(self):
        summary, tasks = fixtures()
        for old_summary, old_tasks in [
            (dict(summary, generated_at='2026-11-17T01:00:00Z'), tasks),
            (summary, dict(tasks, generated_at='2026-11-17T01:00:00Z')),
        ]:
            with self.assertRaises(ValueError):
                unique_sync.changed(summary, tasks, old_summary, old_tasks)

    def test_new_identity_assessment_is_published_even_with_same_counts(self):
        summary, tasks = fixtures()
        assessed = dict(summary, generated_at='2026-11-18T01:01:00Z')
        self.assertTrue(unique_sync.changed(summary, tasks, assessed, tasks))


if __name__ == '__main__':
    unittest.main()

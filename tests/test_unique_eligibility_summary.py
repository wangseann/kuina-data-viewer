"""Current eligibility counts retain their own evidence date and stale-write guard."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import unique_dashboard as dashboard
import unique_sync
from tests.test_unique_dashboard import fixtures


def assessed_summary(at='2026-11-19T19:00:00Z'):
    summary, tasks = fixtures()
    summary.update(schema='kuina-unique-public-summary-v2', eligibility=dict(
        assessed_at=at, quality_manifest_sha256='b' * 64, proof_sha256='c' * 64))
    return summary, tasks


class EligibilitySummaryTests(unittest.TestCase):
    def test_current_counts_show_separate_grouping_and_eligibility_dates(self):
        summary, tasks = assessed_summary()
        original = deepcopy((summary, tasks))
        with tempfile.TemporaryDirectory() as folder:
            dashboard.build(summary, tasks, folder)
            html = (Path(folder) / 'unique.html').read_text()
        self.assertIn('Summary generated 2026-11-18T01:00:00Z', html)
        self.assertIn('Eligibility counts checked 2026-11-19T19:00:00Z', html)
        self.assertIn('Quality catalogue <code>' + 'b' * 64 + '</code>', html)
        self.assertEqual((summary, tasks), original)

    def test_assessment_is_closed_and_cannot_predate_its_grouping(self):
        for key, value in [('assessed_at', '2026-11-17T00:00:00Z'),
                           ('quality_manifest_sha256', 'bad'), ('proof_sha256', 'bad'),
                           ('private_path', '/private/data'), ('notes', 'arbitrary text')]:
            summary, tasks = assessed_summary()
            summary['eligibility'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                dashboard.validate(summary, tasks)
        summary, tasks = assessed_summary()
        del summary['eligibility']
        with self.assertRaises(ValueError):
            dashboard.validate(summary, tasks)

    def test_legacy_summary_discloses_that_eligible_subject_counts_are_saved(self):
        summary, tasks = fixtures()
        with tempfile.TemporaryDirectory() as folder:
            dashboard.build(summary, tasks, folder)
            html = (Path(folder) / 'unique.html').read_text()
        self.assertIn('Eligible subject counts use the saved grouping snapshot', html)

    def test_publication_rejects_older_assessments_and_schema_downgrades(self):
        summary, tasks = assessed_summary()
        old, _ = assessed_summary('2026-11-19T18:00:00Z')
        legacy, _ = fixtures()
        for incoming in (old, legacy):
            with self.assertRaises(ValueError):
                unique_sync.changed(summary, tasks, incoming, tasks)
        self.assertTrue(unique_sync.changed(legacy, tasks, summary, tasks))
        self.assertFalse(unique_sync.changed(summary, tasks, summary, tasks))

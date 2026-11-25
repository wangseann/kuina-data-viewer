from copy import deepcopy
import json
from pathlib import Path
import unittest

import counts
import recovery
import tempfile


class RecoveryTests(unittest.TestCase):
    def test_exact_source_partitions_not_all_statistical_data(self):
        self.assertTrue(recovery.retired_batch(recovery.PARTITIONS[0][0]+'000001'))
        self.assertFalse(recovery.retired_batch('unique-commodities-psd-statistical-other-000001'))
        self.assertFalse(recovery.retired_batch('unique-stocks-prices-review-any-000001'))

    def fixture(self):
        retired = dict(id=recovery.PARTITIONS[0][0]+'000001', definition_sha256='a'*64,
                       category='trade', target_count=1, series_count=7, assignment_enabled=True)
        survivor = dict(id='unique-stocks-identity-000001', definition_sha256='b'*64,
                        category='stocks', target_count=1, series_count=1, assignment_enabled=True)
        catalogue = dict(schema='kuina-public-assignment-catalogue-v1', generation=recovery.GENERATION,
                         batches=[retired,survivor], legacy_definitions=[])
        ledger = dict(assignments={survivor['id']:dict(person='juan',status='active')}, receipts={'14':'preserve'})
        return catalogue,ledger,retired,survivor

    def test_retirement_keeps_surviving_scopes_assignments_and_history(self):
        catalogue,ledger,retired,survivor = self.fixture()
        before = deepcopy((catalogue,ledger))
        result, stats = recovery.retire_catalogue(catalogue,ledger)
        self.assertEqual(result['batches'],[survivor])
        self.assertEqual(result['generation'],catalogue['generation'])
        self.assertEqual(result['legacy_definitions'],[dict(batch_id=retired['id'],definition_sha256='a'*64)])
        self.assertEqual(stats['series'],7)
        self.assertEqual((catalogue,ledger),before)

    def test_retirement_stops_on_an_assigned_exclusion(self):
        catalogue,ledger,retired,_ = self.fixture()
        ledger['assignments'][retired['id']] = dict(person='emily',status='active')
        before = deepcopy((catalogue,ledger))
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            recovery.retire_catalogue(catalogue,ledger)
        self.assertEqual((catalogue,ledger),before)

    def test_main_dashboard_distinguishes_unrecoverable_from_unresolved(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/summary.json').read_text())
        rendered=counts.render(data)
        for marker in ['4,182,499','Confirmed unrecoverable','Confirmed rescue plans awaiting completion',
                       '0 recorded in this assessment','sources.html']:
            self.assertTrue(marker in rendered, 'Missing dashboard element: '+marker)

    def test_no_claim_for_a_different_inventory(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/summary.json').read_text())
        data['types'][0]['excluded_series']+=1
        self.assertEqual(recovery.panel(data),'')

    def test_overview_restores_series_blocks_and_keeps_clean_navigation(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/summary.json').read_text())
        page=counts.render(data)
        for marker in ['One square per identified numeric series', 'data-failure-mask=',
                       'id="series-names-status"', '<script src="quality-series.js" defer></script>',
                       "script-src 'self'; connect-src 'self'", 'data-series-state="eligible"',
                       'data-series-state="excluded"']:
            self.assertTrue(marker in page, 'Missing restored block feature: '+marker)
        for marker in ['Current usable data','Find new data','Assignments','Detailed audit and methods','quality-details.html']:
            self.assertTrue(marker in page, 'Missing current dashboard route: '+marker)

    def test_old_snapshot_is_readable_but_cannot_be_republished_as_active_work(self):
        from test_unique_dashboard import fixtures
        import unique_dashboard
        import unique_sync
        summary,tasks=fixtures()
        tasks['batches'][0]['id']=recovery.PARTITIONS[0][0]+'000001'
        self.assertTrue(unique_dashboard.validate(summary,tasks))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'unrecoverable'):
                unique_dashboard.build(summary,tasks,folder)
        with self.assertRaisesRegex(ValueError,'unrecoverable'):
            unique_sync.artifacts(summary,tasks)


if __name__ == '__main__':
    unittest.main()

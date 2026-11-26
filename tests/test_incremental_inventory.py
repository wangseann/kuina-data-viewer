import copy,json,unittest
from pathlib import Path
import counts,recovery

class IncrementalInventoryTests(unittest.TestCase):
    def test_new_eligible_upload_does_not_hide_frozen_source_limits(self):
        summary=json.loads((Path(__file__).parents[1]/'docs/summary.json').read_text())
        before=recovery.panel(summary)
        row=next(r for r in summary['types'] if r['id']=='crypto')
        row['confirmed_series']+=1;row['confirmed_units']+=1
        summary['assessment_utc']='2026-11-26T01:00:00+00:00'
        counts.validate(summary)
        after=recovery.panel(summary)
        self.assertIn('4,182,499',after);self.assertIn('Confirmed unrecoverable',after)
        self.assertIn('Upload audit status',counts.render(summary))

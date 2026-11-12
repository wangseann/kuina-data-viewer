from pathlib import Path
import subprocess
import unittest

from counts import render, validate, eligible_grid, failure_waffle
from test_failure_colours import snapshot

ROOT = Path(__file__).resolve().parent.parent


class SeriesHoverTests(unittest.TestCase):
    def test_grids_expose_type_state_and_exact_failure_masks(self):
        page = render(validate(snapshot()))
        self.assertIn('data-series-type="stocks" data-series-state="eligible"', page)
        self.assertIn('data-series-type="stocks" data-series-state="excluded"', page)
        for mask in (1, 2, 7):
            self.assertIn(f'data-failure-mask="{mask}"', page)
        self.assertIn('<script src="quality-series.js" defer></script>', page)
        self.assertIn("script-src 'self'; connect-src 'self'", page)
        self.assertIn('id="series-names-status"', page)

    def test_named_tile_metadata_preserves_display_caps_and_rare_masks(self):
        eligible = eligible_grid(30000, 'stocks')
        excluded = failure_waffle([dict(mask=1, count=100000), dict(mask=15, count=1)], 'stocks')
        self.assertEqual(eligible.count('class="square confirmed-square"'), 20000)
        self.assertEqual(excluded.count('data-failure-mask="1"'), 3999)
        self.assertEqual(excluded.count('data-failure-mask="15"'), 1)
        self.assertIn('30,000', eligible)
        self.assertIn('100,001', excluded)

    def test_public_names_contract(self):
        subprocess.run(['node', str(ROOT / 'tests/test_quality_series.js')], check=True, capture_output=True)

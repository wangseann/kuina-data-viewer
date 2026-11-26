import importlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess


class AcquisitionTests(unittest.TestCase):
    def test_market_sector_coverage_priorities_and_proxy_limits_are_explicit(self):
        module=importlib.import_module('acquisition')
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        sectors={r['sector'] for r in data['sources'] if r['id'].startswith('equity-sector-')}
        self.assertEqual(sectors, {'Communication services','Consumer discretionary','Consumer staples',
            'Energy','Financials','Health care','Industrials','Materials','Real estate','Technology','Utilities'})
        self.assertTrue(any(r['market']=='bonds' for r in data['sources']))
        self.assertTrue(any(r['provider']=='EV Trading Labs' and r['market']=='forex' for r in data['sources']))
        self.assertTrue(all(r['access'] in {'public_archive','free_login'} for r in data['sources']))
        page=module.render(data)
        for marker in ['Market and sector coverage priorities','G10 majors', 'agriculture', 'livestock',
                       'inflation-linked', 'No qualifying free direct-price archive confirmed',
                       'do not close gaps', 'lower priority']:
            self.assertTrue(marker in page, 'Missing coverage policy: '+marker)

    def test_market_sector_and_status_filters_compose(self):
        module=importlib.import_module('acquisition')
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'filters.js';script.write_text(module.SCRIPT)
            subprocess.run(['node',str(Path(__file__).with_name('test_source_filters.js')),str(script)],check=True,capture_output=True)

    def test_current_search_log_has_market_sector_and_unverified_collection_status(self):
        module=importlib.import_module('acquisition')
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        module.validate(data)
        self.assertGreater(len(data['sources']),0)
        self.assertTrue(all(r['access'] in {'public_archive','free_login'} for r in data['sources']))
        self.assertTrue(all(r['market'] and r['sector'] and r['next_step'] for r in data['sources']))
        self.assertFalse(any(r['status']=='eligible' for r in data['sources']))
        with tempfile.TemporaryDirectory() as folder:
            module.build(data,folder)
            rendered=(Path(folder)/'sources.html').read_text()
        for marker in ['Find new data','Free sources only','Market','Sector','Provider','Next check','No data downloaded','market-filter','sector-filter']:
            self.assertTrue(marker in rendered,'Missing source tracker element: '+marker)

    def test_source_log_rejects_credentials_private_fields_and_unproved_eligibility(self):
        module=importlib.import_module('acquisition')
        base=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        for key,value in [('private_path','/private/data'),('source_url','https://example.com/?api_key=SECRET'),('status','eligible'),('access','paid'),('access','plan_check')]:
            data=json.loads(json.dumps(base));data['sources'][0][key]=value
            with self.assertRaises(ValueError):module.validate(data)

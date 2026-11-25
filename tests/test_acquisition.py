import importlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess


class AcquisitionTests(unittest.TestCase):
    def test_market_sector_and_status_filters_compose(self):
        module=importlib.import_module('acquisition')
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'filters.js';script.write_text(module.SCRIPT)
            subprocess.run(['node',str(Path(__file__).with_name('test_source_filters.js')),str(script)],check=True,capture_output=True)

    def test_current_search_log_has_market_sector_and_unverified_collection_status(self):
        module=importlib.import_module('acquisition')
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        module.validate(data)
        self.assertGreaterEqual(len(data['sources']),10)
        self.assertTrue(all(r['market'] and r['sector'] and r['next_step'] for r in data['sources']))
        self.assertFalse(any(r['status']=='eligible' for r in data['sources']))
        with tempfile.TemporaryDirectory() as folder:
            module.build(data,folder)
            rendered=(Path(folder)/'sources.html').read_text()
        for marker in ['Find new data','Market','Sector','Provider','Next check','No data downloaded','market-filter','sector-filter']:
            self.assertTrue(marker in rendered,'Missing source tracker element: '+marker)

    def test_source_log_rejects_credentials_private_fields_and_unproved_eligibility(self):
        module=importlib.import_module('acquisition')
        base=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        for key,value in [('private_path','/private/data'),('source_url','https://example.com/?api_key=SECRET'),('status','eligible')]:
            data=json.loads(json.dumps(base));data['sources'][0][key]=value
            with self.assertRaises(ValueError):module.validate(data)

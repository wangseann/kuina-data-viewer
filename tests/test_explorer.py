from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class ExplorerTests(unittest.TestCase):
    def test_eligibility_and_coverage_semantics(self):
        subprocess.run(['node', str(ROOT / 'tests/test_explorer_core.js')], check=True, capture_output=True)

    def test_private_files_have_no_upload_or_execution_path(self):
        page = (ROOT / 'docs/explorer.html').read_text()
        source = (ROOT / 'docs/explorer.js').read_text()
        self.assertIn("connect-src 'none'", page)
        self.assertIn('webkitdirectory', page)
        self.assertNotIn('<iframe', page)
        for forbidden in ['fetch(', 'XMLHttpRequest', 'eval(', 'innerHTML', 'srcdoc']:
            self.assertNotIn(forbidden, source)
        self.assertNotIn('/datashare/', page)
        self.assertNotIn('type="application/octet-stream"', page)


if __name__ == '__main__':
    unittest.main()

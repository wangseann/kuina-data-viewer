from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TaskPageTests(unittest.TestCase):
    def test_public_snapshot_contract(self):
        subprocess.run(['node', str(ROOT / 'tests/test_tasks_core.js')], check=True, capture_output=True)

    def test_board_cannot_claim_from_a_static_browser(self):
        page = (ROOT / 'docs/tasks.html').read_text()
        source = (ROOT / 'docs/tasks.js').read_text()
        self.assertIn("connect-src 'self'", page)
        self.assertIn('authoritative', page)
        for forbidden in ['localStorage', 'innerHTML', 'eval(', '/datashare/', 'method:']:
            self.assertNotIn(forbidden, source)
        self.assertIn('tasks-summary.json', source)


if __name__ == '__main__':
    unittest.main()

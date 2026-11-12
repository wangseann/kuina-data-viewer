import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coordination.claim_service import run


class ServiceTests(unittest.TestCase):
    def test_pending_publication_survives_and_retries_without_new_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'config.json'
            config.write_text(json.dumps({'publisher': ['python3', 'publisher.py']}))
            state = root/'state.json'
            receipt = root/'receipt.json'
            with patch('coordination.claim_service.poll', return_value=[{'status':'confirmed'}]), patch('coordination.claim_service.subprocess.run') as publish:
                publish.return_value.returncode = 1
                run(config,state,receipt)
            self.assertTrue(json.loads(state.read_text())['sync_pending'])
            with patch('coordination.claim_service.poll', return_value=[]), patch('coordination.claim_service.subprocess.run') as publish:
                publish.return_value.returncode = 0
                run(config,state,receipt)
                publish.assert_called_once()
            self.assertFalse(json.loads(state.read_text())['sync_pending'])

    def test_idle_poll_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'config.json'
            config.write_text('{}')
            with patch('coordination.claim_service.poll', return_value=[]), patch('coordination.claim_service.subprocess.run') as publish:
                result = run(config,root/'state.json',root/'receipt.json')
                publish.assert_not_called()
                self.assertEqual(result['status'],'CHECKED')

if __name__ == '__main__':
    unittest.main()

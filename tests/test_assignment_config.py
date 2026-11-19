import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from coordination.assignment_config import PublicCatalogue, make_backend


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'catalogue.json'
        self.value = dict(schema='kuina-public-assignment-catalogue-v1', generation='a' * 64,
                          batches=[dict(id='unique-test-000001', category='stocks', target_count=1,
                                        series_count=5, definition_sha256='b' * 64, assignment_enabled=True)])

    def write(self):
        raw = json.dumps(self.value).encode()
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_only_pinned_closed_public_batch_metadata_is_accepted(self):
        catalogue = PublicCatalogue(self.path, self.write())
        row = catalogue('unique-test-000001')
        self.assertEqual(row['generation'], 'a' * 64)
        self.assertEqual(row['definition_sha256'], 'b' * 64)
        with self.assertRaises(ValueError):
            catalogue('unknown')
        self.path.write_text('{}')
        with self.assertRaises(ValueError):
            catalogue('unique-test-000001')

    def test_private_keys_duplicates_and_wrong_hash_fail_closed(self):
        for change in (lambda v: v.update(private_path='/private'),
                       lambda v: v['batches'].append(dict(v['batches'][0])),
                       lambda v: v['batches'][0].update(uid=11198)):
            original = json.loads(json.dumps(self.value))
            change(self.value)
            with self.assertRaises(ValueError):
                PublicCatalogue(self.path, self.write())
            self.value = original
        self.write()
        with self.assertRaises(ValueError):
            PublicCatalogue(self.path, '0' * 64)

    def test_unspecified_legacy_route_preserved_unknown_authority_rejected(self):
        native = object()
        self.assertIs(make_backend({}, None, native), native)
        with self.assertRaises(ValueError):
            make_backend(dict(assignment_authority='something'), None, native)


if __name__ == '__main__':
    unittest.main()

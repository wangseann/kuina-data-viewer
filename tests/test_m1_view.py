import copy
import unittest

from m1_view import render, validate


def snapshot():
    fields = ('open', 'high', 'low', 'close', 'volume')
    return dict(schema='kuina-m1-audit-public-v1', audit_utc='2026-11-13T01:02:03Z',
        window_start='2024-10-01', window_end_exclusive='2026-10-01',
        requirements=dict(max_native_seconds=900, min_history_years=2),
        types=[dict(id='currencies', instrument_count=1, series_count=5,
            eligible_count=4, failed_count=1,
            check_failures=[dict(id='timestamp_timezone', count=1)],
            series=[dict(id=f'{index:064x}', label='EURUSD', variable=field,
                source='Dukascopy bank CSV', native_seconds=60,
                mask=8 if field == 'volume' else 0)
                for index, field in enumerate(fields)])])


class M1ViewTests(unittest.TestCase):
    def test_valid_snapshot_is_unchanged(self):
        data = snapshot()
        previous = copy.deepcopy(data)
        self.assertIs(validate(data), data)
        self.assertEqual(data, previous)

    def test_private_payload_rejected_at_every_level(self):
        for target in ('root', 'type', 'series', 'check', 'requirements'):
            data = snapshot()
            containers = dict(root=data, type=data['types'][0],
                series=data['types'][0]['series'][0], check=data['types'][0]['check_failures'][0],
                requirements=data['requirements'])
            containers[target]['observations'] = [42]
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate(data)

    def test_bad_dates_counts_fields_and_duplicate_ids_rejected(self):
        changes = [lambda d: d.update(audit_utc='2026-11-13'),
            lambda d: d.update(window_end_exclusive='2025-10-01'),
            lambda d: d['types'][0].update(eligible_count=True),
            lambda d: d['types'][0].update(failed_count=0),
            lambda d: d['types'][0].update(instrument_count=2),
            lambda d: d['types'][0].update(series_count=20001),
            lambda d: d['requirements'].update(min_history_years=True),
            lambda d: d['types'][0]['series'][0].update(variable='adjusted_close'),
            lambda d: d['types'][0]['series'][0].update(native_seconds=True),
            lambda d: d['types'][0]['series'][0].update(mask=16),
            lambda d: d['types'][0]['series'][1].update(id=d['types'][0]['series'][0]['id']),
            lambda d: d['types'].append(copy.deepcopy(d['types'][0])),
            lambda d: d['types'][0]['check_failures'][0].update(id='arbitrary_text'),
            lambda d: d['types'][0]['check_failures'][0].update(count=2)]
        for change in changes:
            data = snapshot()
            change(data)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(data)

    def test_private_names_and_providers_rejected(self):
        for field, value in [('label', '/datashare/private/name'),
                             ('label', 'https://example.com/private'),
                             ('label', 'name\nsecret'), ('source', 'private feed')]:
            data = snapshot()
            data['types'][0]['series'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate(data)

    def test_render_shows_every_tile_and_exact_audit_epoch(self):
        data = snapshot()
        data['types'][0]['series'][0]['label'] = 'EUR & USD <spot>'
        page = render(data)
        self.assertEqual(page.count('class="tile"'), 5)
        self.assertIn('2026-11-13T01:02:03Z', page)
        self.assertIn('EUR &amp; USD &lt;spot&gt;', page)
        self.assertIn('name="dataset"', page)
        self.assertIn('Timestamp timezone', page)
        self.assertIn('background:#25826b', page)
        self.assertIn('#7b8795', page)
        self.assertIn('Source: Dukascopy bank CSV', page)
        self.assertNotIn('fetch(', page)

    def test_placeholder_has_no_tiles_or_invented_audit_epoch(self):
        page = render(None)
        self.assertIn('Not yet published', page)
        self.assertNotIn('class="tile"', page)
        self.assertNotIn('2026-11-13', page)

    def test_attention_labels_distinguish_audited_but_unverified_details(self):
        data = snapshot()
        data['types'][0]['check_failures'] = [dict(id=identifier, count=1) for identifier in
            ('calendar', 'price_definition', 'completeness', 'history_span', 'window_months', 'timestamp_timezone')]
        page = render(data)
        for label in ('Results needing attention', 'Trading hours not established',
                      'Price side, adjustments or volume units not established',
                      'Missing periods cannot be verified', 'Less than two years of usable history',
                      'Months missing from the testing window', 'Timestamp timezone'):
            self.assertIn(label, page)
        self.assertIn('Every series listed here was checked.', page)
        self.assertIn('those checks remain unverified', page)
        self.assertIn('does not show that prices are wrong', page)
        self.assertNotIn('Checks that failed or remain unfinished', page)

    def test_combined_failures_and_dataset_selection_are_preserved(self):
        data = snapshot()
        data['types'][0]['series'][-1]['mask'] = 9
        second = copy.deepcopy(data['types'][0])
        second['id'] = 'stocks'
        for index, record in enumerate(second['series']):
            record['id'] = f'{index + 5:064x}'
        data['types'].append(second)
        page = render(data)
        self.assertEqual(page.count('class="tile"'), 10)
        self.assertIn('linear-gradient(135deg,#237cb6 0% 50%,#7b8795 50% 100%)', page)
        self.assertIn('#dataset-1:checked~.dataset-1{display:block}', page)
        self.assertEqual(page.count(' checked>'), 1)
        self.assertIn('.dataset{display:none}', page)


if __name__ == '__main__':
    unittest.main()

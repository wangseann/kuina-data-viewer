import unittest

from counts import IDS, render, validate
from failure_codes import classify_reasons, reassess


def record(seconds=60, longest=0, history=True, price=True):
    checks = [
        dict(id='history_span', status='PASS' if history else 'FAIL',
             reason=None if history else 'short_history',
             kind=None if history else 'measured_failure', evidence=history),
    ]
    if price:
        checks += [
            dict(id='native_cadence', status='PASS', reason=None, kind=None, evidence=seconds),
            dict(id='longest_gap', status='PASS', reason=None, kind=None, evidence=longest),
        ]
    return dict(native_seconds=seconds, checks=checks,
                coverage=dict(longest_missing_seconds=longest), field='close')


def snapshot():
    rows = [dict(id=identifier, confirmed_series=0, confirmed_units=0,
                 excluded_series=0, excluded_measured=0, excluded_missing_evidence=0,
                 source_failures=0, issues=[], failure_masks=[]) for identifier in IDS]
    rows[0].update(confirmed_series=1, confirmed_units=1, excluded_series=3,
                   excluded_measured=3, issues=[dict(id='hourly_gaps', count=2),
                   dict(id='coarse_resolution', count=2), dict(id='short_history', count=1)],
                   failure_masks=[dict(mask=1, count=1), dict(mask=2, count=1), dict(mask=7, count=1)])
    return dict(schema=4, audit_utc='2026-11-09T14:39:02+00:00',
                assessment_utc='2026-11-10T01:00:00+00:00',
                requirements=dict(max_native_seconds=900, min_history_years=2), types=rows)


class FailureColourTests(unittest.TestCase):
    def test_hourly_now_fails_and_quarter_hour_passes(self):
        self.assertIn('coarse_resolution', reassess(record(seconds=3600))['reasons'])
        self.assertEqual(reassess(record(seconds=900))['decision'], 'ELIGIBLE')

    def test_context_also_needs_the_requested_resolution(self):
        self.assertIn('coarse_resolution', reassess(record(seconds=86400, price=False))['reasons'])

    def test_minute_series_cannot_hide_a_half_hour_hole(self):
        self.assertIn('long_gaps', reassess(record(longest=1740))['reasons'])
        self.assertEqual(reassess(record(longest=840))['decision'], 'ELIGIBLE')

    def test_missing_cadence_is_unknown_not_a_measured_coarse_interval(self):
        result = reassess(record(seconds=None, price=False))
        self.assertEqual(result['failure_mask'], 8)
        self.assertIn('cadence_unknown', result['reasons'])

    def test_overlapping_failures_keep_all_colours_without_double_counting(self):
        result = reassess(record(seconds=3600, longest=3600, history=False))
        self.assertEqual(result['failure_mask'], 7)
        self.assertEqual(classify_reasons(['calendar_unverified']), 8)
        data = snapshot()
        validate(data)
        page = render(data)
        self.assertEqual(page.count('class="square failed-square'), 3)
        self.assertIn('failure-mask-stocks-7', page)
        for colour in ['#237cb6', '#e18c1f', '#8654a8']:
            self.assertIn(colour, page)
        self.assertIn('Several colours', page)

    def test_public_schema_rejects_inconsistent_masks_and_private_payloads(self):
        for mutate in [
            lambda d: d['types'][0]['failure_masks'][0].update(count=2),
            lambda d: d['types'][0]['failure_masks'][0].update(mask=True),
            lambda d: d['types'][0]['failure_masks'][0].update(mask=16),
            lambda d: d['types'][0]['failure_masks'][0].update(ticker='forbidden'),
            lambda d: d['requirements'].update(max_native_seconds=3600),
        ]:
            data = snapshot()
            mutate(data)
            with self.assertRaises(ValueError):
                validate(data)


if __name__ == '__main__':
    unittest.main()

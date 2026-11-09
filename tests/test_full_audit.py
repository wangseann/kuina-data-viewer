import unittest,copy
from counts import validate,render,IDS


def full_snapshot():
    rows=[dict(id=i,confirmed_series=0,confirmed_units=0,excluded_series=0,excluded_measured=0,excluded_missing_evidence=0,source_failures=0,issues=[])for i in IDS]
    rows[0].update(confirmed_series=7,confirmed_units=1)
    rows[2].update(excluded_series=3,excluded_measured=2,excluded_missing_evidence=1,issues=[dict(id='coarse_resolution',count=2),dict(id='calendar_unverified',count=1)])
    rows[8].update(excluded_series=2,excluded_missing_evidence=2,issues=[dict(id='scrape_completeness',count=2)])
    return dict(schema=3,audit_utc='2026-11-09T15:00:00Z',types=rows)

class FullAuditTests(unittest.TestCase):
    def test_all_excluded_series_are_red_including_missing_evidence(self):
        data=full_snapshot();validate(data);page=render(data)
        self.assertEqual(page.count('class="square failed-square"'),5)
        self.assertEqual(page.count('class="square confirmed-square"'),7)
        self.assertNotIn('need checks',page.lower())
        self.assertIn('Required evidence missing',page)
        self.assertIn('Financial prices are coarser than hourly',page)

    def test_full_scope_counts_cannot_be_added_incorrectly(self):
        data=full_snapshot();data['types'][2]['excluded_series']=4
        with self.assertRaises(ValueError):validate(data)

    def test_data_payload_and_unknown_reason_are_rejected(self):
        for key,value in [('observations',[1]),('ticker','forbidden identifier')]:
            data=full_snapshot();data['types'][0][key]=value
            with self.assertRaises(ValueError):validate(data)
        data=full_snapshot();data['types'][2]['issues'][0]['id']='arbitrary confidential message'
        with self.assertRaises(ValueError):validate(data)

    def test_excluded_series_need_an_explicit_reason_breakdown(self):
        data=full_snapshot();data['types'][2]['issues']=[]
        with self.assertRaises(ValueError):validate(data)

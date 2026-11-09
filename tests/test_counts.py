import unittest
from counts import validate, render, totals


def snapshot():
    from counts import IDS
    rows=[dict(id=name,confirmed_series=0,confirmed_units=0,provisional_series=0,additional_failed=0,additional_review=0,unvalidated_groups=0) for name in IDS]
    rows[IDS.index('stocks')].update(confirmed_series=6265,confirmed_units=895)
    rows[IDS.index('crypto')].update(confirmed_series=72,confirmed_units=8)
    rows[IDS.index('sentiment')].update(provisional_series=129)
    return dict(schema=1,audit_utc='2026-11-06T09:48:00+00:00',types=rows)


class CountsTests(unittest.TestCase):
    def test_confirmed_and_provisional_are_separate(self):
        data=validate(snapshot())
        self.assertEqual(totals(data),(6337,129))
        html=render(data)
        self.assertIn('6,337',html)
        self.assertIn('129',html)
        self.assertIn('Provisional',html)
        self.assertNotIn('6,466 confirmed',html)

    def test_observation_fields_are_rejected(self):
        data=snapshot();data['prices']=[100,101]
        with self.assertRaises(ValueError):validate(data)
        data=snapshot();data['types'][0]['observations']=[1,2]
        with self.assertRaises(ValueError):validate(data)

    def test_boolean_and_negative_counts_are_rejected(self):
        for bad in [True,-1,1.5]:
            data=snapshot();data['types'][0]['confirmed_series']=bad
            with self.assertRaises(ValueError):validate(data)

    def test_duplicate_category_and_unknown_dates_are_rejected(self):
        data=snapshot();data['types'][0]['id']=data['types'][1]['id']
        with self.assertRaises(ValueError):validate(data)
        data=snapshot();data['audit_utc']='not-an-audit-date'
        with self.assertRaises(ValueError):validate(data)


if __name__=='__main__':unittest.main()

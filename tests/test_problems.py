import unittest
from html.parser import HTMLParser
from counts import validate,render,totals
from test_counts import snapshot


def with_problems():
    data=snapshot();data['schema']=2
    for row in data['types']:row['issues']=[]
    data['types'][2].update(additional_failed=3,additional_review=2,issues=[
        dict(id='short_history',count=3),dict(id='calendar_unverified',count=2)])
    return data


class Text(HTMLParser):
    def __init__(self,page):
        super().__init__();self.parts=[];self.feed(page)
    def handle_data(self,data):self.parts.append(data)


class ProblemsTests(unittest.TestCase):
    def test_reasons_render_without_promoting_series(self):
        data=with_problems()
        try:page=render(data)
        except ValueError as exc:self.fail('Aggregate issue counts should be supported: '+str(exc))
        text=' '.join(Text(page).parts)
        self.assertIn('Less than two years of valid history',text)
        self.assertIn('Trading / reporting calendar not verified',text)
        self.assertIn('One field can have several problems',text)
        self.assertIn('No assessed series in this snapshot',text)
        self.assertEqual(totals(data),(6337,129))
        self.assertEqual(page.count('class="square confirmed-square"'),6337)

    def test_reason_payload_cannot_include_data_or_arbitrary_text(self):
        for issue in [dict(id='prices',count=1),dict(id='short_history',count=1,values=[100]),
                      dict(id='short_history',count=True),dict(id='short_history',count=-1)]:
            data=with_problems();data['types'][2]['issues']=[issue]
            with self.assertRaises(ValueError):validate(data)

    def test_duplicate_and_impossible_reason_counts_rejected(self):
        for issues in [[dict(id='short_history',count=1)]*2,[dict(id='short_history',count=6)]]:
            data=with_problems();data['types'][2]['issues']=issues
            with self.assertRaises(ValueError):validate(data)


if __name__=='__main__':unittest.main()

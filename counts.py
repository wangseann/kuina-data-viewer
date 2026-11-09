"""Build a public dashboard from an explicit counts-only metadata schema."""
import argparse
from datetime import datetime
import html
import json
from pathlib import Path

LABELS={
    'stocks':'Stocks / ETFs','crypto':'Crypto','commodities':'Commodities',
    'currencies':'Currencies','derivatives':'Derivatives','economics':'Economics',
    'gdelt':'GDELT / news','prediction-markets':'Prediction markets',
    'sentiment':'Tweets / Sentiments','emotions':'Emotions','trade':'Trade',
    'weather':'Weather / rivers','reddit':'Reddit','other-markets':'Indices / bonds / other',
}
IDS=list(LABELS)
COUNTS={'confirmed_series','confirmed_units','provisional_series','additional_failed','additional_review','unvalidated_groups'}


def validate(data):
    if not isinstance(data,dict) or set(data)!={'schema','audit_utc','types'} or type(data['schema']) is not int or data['schema']!=1:
        raise ValueError('Only the counts-only schema is accepted')
    if not isinstance(data['audit_utc'],str):
        raise ValueError('Audit time must be an ISO timestamp')
    when=datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00'))
    if when.tzinfo is None:
        raise ValueError('Audit time must include a timezone')
    if not isinstance(data['types'],list) or len(data['types'])!=len(IDS):
        raise ValueError('Every dataset type must occur exactly once')
    seen=set()
    for row in data['types']:
        if not isinstance(row,dict) or set(row)!=COUNTS|{'id'} or row['id'] not in IDS or row['id'] in seen:
            raise ValueError('Unexpected fields or duplicate dataset type')
        seen.add(row['id'])
        if any(type(row[key]) is not int or not 0<=row[key]<=10**9 for key in COUNTS):
            raise ValueError('Counts must be nonnegative integers')
        if row['confirmed_units']>row['confirmed_series']:
            raise ValueError('Confirmed units cannot exceed numeric series')
    return data


def totals(data):
    return (sum(row['confirmed_series'] for row in data['types']),
            sum(row['provisional_series'] for row in data['types']))


def render(data):
    validate(data)
    confirmed,provisional=totals(data)
    rows={row['id']:row for row in data['types']}
    primary=[];review=[]
    for identifier,label in LABELS.items():
        row=rows[identifier]
        cells=[html.escape(label),f"{row['confirmed_series']:,}",f"{row['confirmed_units']:,}",f"{row['provisional_series']:,}"]
        primary.append('<tr><th scope="row">'+cells[0]+'</th><td class="confirmed">'+cells[1]+'</td><td>'+cells[2]+'</td><td class="provisional">'+cells[3]+'</td></tr>')
        review.append('<tr><th scope="row">'+html.escape(label)+'</th>'+''.join('<td>'+f'{row[key]:,}'+'</td>' for key in ['additional_failed','additional_review','unvalidated_groups'])+'</tr>')
    audit=html.escape(datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00')).strftime('%d %B %Y'))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="1800"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Kuina · Dataset quality</title><style>
:root{color-scheme:light;--ink:#18283a;--muted:#586c7c;--line:#dbe2e9}*{box-sizing:border-box}body{font:15px system-ui,sans-serif;color:var(--ink);background:#f2f5f7;margin:0}main{max-width:1100px;margin:auto;padding:32px 22px}h1{margin:0;font-size:32px;letter-spacing:-1px}h2{font-size:20px}p{line-height:1.6;color:var(--muted)}.cards{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px 24px;flex:1;min-width:220px}.card strong{display:block;font-size:36px;color:#216f57}.card.orange strong{color:#9a5f0d}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}.wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:11px 12px;text-align:right}th:first-child{text-align:left}thead th{font-size:12px;color:var(--muted)}.confirmed{background:#eff8f3}.provisional{background:#fff6e8}.small{font-size:12px}.tag{font:11px ui-monospace,monospace;letter-spacing:1.5px;text-transform:uppercase;color:#2d755f}details summary{cursor:pointer;font-weight:600}a{color:#27648b}footer{margin:24px 0}</style></head><body><main>
<div class="tag">Kuina · Public quality counts</div><h1>Which series meet our requirements?</h1>
<p>Last verified audit: <strong>'''+audit+'''</strong>. This page refreshes every 30 minutes. Daily publishing checks for a newer verified summary; it does not run a new data audit.</p>
<div class="cards"><div class="card"><strong>'''+f'{confirmed:,}'+'''</strong>Confirmed numeric series</div><div class="card orange"><strong>'''+f'{provisional:,}'+'''</strong>Provisional sentiment signals · not included in confirmed total</div></div>
<section class="panel"><h2>Confirmed counts by dataset type</h2><p class="small">One numeric field is one series. For example, open, high, low and close count separately. Zero means none confirmed, not that no data exist.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Confirmed series</th><th>Confirmed assets / accounts</th><th>Provisional signals</th></tr></thead><tbody>'''+''.join(primary)+'''</tbody></table></div></section>
<details class="panel"><summary>Other available data and remaining checks</summary><p class="small">These counts concern the additional-source audit. They are separate source variants and may overlap the confirmed registry; do not add them together. Fields without numeric observations are excluded. Groups without a validated table can be support snapshots or unresolved schemas.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Failed measured checks</th><th>Needs further checks</th><th>No validated table</th></tr></thead><tbody>'''+''.join(review)+'''</tbody></table></div><p class="small">Unresolved checks include market calendars, price construction and adjustment, historical release timing, revisions and source formats. The 129 provisional sentiment signals have supported derived grids; scrape completeness and processing availability are not fully certified.</p></details>
<details class="panel"><summary>Requirements and update policy</summary><p>Financial prices need at least two calendar years of actual history, hourly or finer native observations (15 minutes preferred), valid values and no unexplained empty expected hourly blocks under the correct calendar. Context retains its own native cadence and needs coverage and availability evidence.</p><p>No price observations, sentiment values, timestamp arrays, credentials, participant information or delegation tasks are published here. The data and task hub remain in private project storage.</p><p>Counts only change after an approved audit snapshot is published. If no new audit is available, the last-audit date stays unchanged.</p></details><footer class="small"><a href="summary.json">Download public counts metadata</a></footer></main></body></html>'''


def build(data,directory):
    validate(data)
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    (directory/'index.html').write_text(render(data))
    (directory/'.nojekyll').touch()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'docs')
    args=parser.parse_args()
    build(json.loads(args.input.read_text()),args.out)

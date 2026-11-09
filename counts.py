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
ISSUES={
    'short_history':('Less than two years of valid history','failed'),
    'coarse_resolution':('Price observations are coarser than hourly','failed'),
    'missing_months':('Price data do not span every month of the test window','failed'),
    'no_window_data':('No valid observations in the test window','failed'),
    'no_valid_observations':('Numeric values exist, but no valid timed observations remain','failed'),
    'hourly_gaps':('Empty expected hourly blocks','failed'),
    'long_gaps':('An observed gap exceeds the accepted hourly limit','failed'),
    'invalid_values':('Invalid numeric observations in the test window','failed'),
    'invalid_times':('Unparseable observation timestamps','failed'),
    'conflicting_duplicates':('Different values share the same timestamp','failed'),
    'inconsistent_ohlc':('Inconsistent open / high / low / close candles','failed'),
    'other_failed_checks':('Other recorded coverage or value failure','failed'),
    'cadence_unknown':('Native observation interval not established','review'),
    'calendar_unverified':('Trading / reporting calendar not verified','review'),
    'provisional_calendar_gaps':('Possible gaps on a provisional calendar; needs verification','review'),
    'price_definition_unverified':('Price definition / adjustment not verified','review'),
    'availability_unverified':('Historical availability / release timing not verified','review'),
    'context_gaps':('Missing expected contextual reporting periods','review'),
    'parse_errors':('Some source files could not be fully parsed','review'),
    'scrape_completeness':('Tweet scrape completeness not certified','review'),
    'other_review_checks':('Other recorded verification still required','review'),
}


def validate(data):
    if not isinstance(data,dict) or set(data)!={'schema','audit_utc','types'} or type(data['schema']) is not int or data['schema'] not in (1,2):
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
        fields=COUNTS|{'id'}
        if data['schema']==2:fields=fields|{'issues'}
        if not isinstance(row,dict) or set(row)!=fields or not isinstance(row['id'],str) or row['id'] not in IDS or row['id'] in seen:
            raise ValueError('Unexpected fields or duplicate dataset type')
        seen.add(row['id'])
        if any(type(row[key]) is not int or not 0<=row[key]<=10**9 for key in COUNTS):
            raise ValueError('Counts must be nonnegative integers')
        if row['confirmed_units']>row['confirmed_series']:
            raise ValueError('Confirmed units cannot exceed numeric series')
        if data['schema']==2:
            if not isinstance(row['issues'],list) or len(row['issues'])>len(ISSUES):
                raise ValueError('Only aggregate issue counts are accepted')
            issue_ids=set()
            available=row['additional_failed']+row['additional_review']+row['provisional_series']
            for issue in row['issues']:
                if not isinstance(issue,dict) or set(issue)!={'id','count'} or not isinstance(issue['id'],str) or issue['id'] not in ISSUES or issue['id'] in issue_ids:
                    raise ValueError('Unexpected or duplicate issue ID')
                if type(issue['count']) is not int or not 0<issue['count']<=available:
                    raise ValueError('Issue counts must refer to assessed, unconfirmed fields')
                issue_ids.add(issue['id'])
    return data


def totals(data):
    return (sum(row['confirmed_series'] for row in data['types']),
            sum(row['provisional_series'] for row in data['types']))


def waffle(count,provisional=False):
    if not count:
        return '<span class="small">0 confirmed</span>'
    shown=min(count,20000)
    columns=160;pitch=4;height=((shown+columns-1)//columns)*pitch
    kind='provisional-square' if provisional else 'confirmed-square'
    label='provisional' if provisional else 'confirmed'
    squares=''.join(f'<rect class="square {kind}" x="{i%columns*pitch}" y="{i//columns*pitch}" width="3" height="3"/>' for i in range(shown))
    note=f'<span class="small">First {shown:,} of {count:,} shown</span>' if shown<count else ''
    return f'<svg viewBox="0 0 640 {height}" role="img" aria-label="{count:,} {label} numeric series">{squares}</svg>'+note


def problem_section(data):
    rows={row['id']:row for row in data['types']}
    parts=[]
    for identifier,label in LABELS.items():
        row=rows[identifier]
        issues=row.get('issues',[])
        body=[]
        for issue in sorted(issues,key=lambda item:(ISSUES[item['id']][1],-item['count'],item['id'])):
            description,kind=ISSUES[issue['id']]
            status='Measured failure' if kind=='failed' else 'Needs verification'
            body.append(f'<tr><th scope="row">{html.escape(description)}</th><td>{issue["count"]:,}</td><td class="{kind}">{status}</td></tr>')
        assessed=row['additional_failed']+row['additional_review']+row['provisional_series']
        if body:
            content='<div class="wrap"><table><thead><tr><th>Problem</th><th>Affected fields / signals</th><th>Evidence</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
        elif assessed:
            content='<p>Reason breakdown not supplied in this snapshot; this is not a pass.</p>'
        elif row['confirmed_series']:
            content='<p>No additional excluded series assessed in this snapshot.</p>'
        else:
            content='<p>No assessed series in this snapshot. This is not evidence that no data exist.</p>'
        if row['unvalidated_groups']:
            content+=f'<p class="small">{row["unvalidated_groups"]:,} source groups have no validated observation table. These are groups, not series; their format, schema or observation role remains unresolved.</p>'
        summary=f'{html.escape(label)} · {row["additional_failed"]:,} failed · {row["additional_review"]:,} need checks'
        if row['provisional_series']:summary+=f' · {row["provisional_series"]:,} provisional'
        parts.append(f'<details class="issue-type" id="issues-{identifier}"><summary>{summary}</summary>{content}</details>')
    return '<section class="panel" id="problems"><h2>Why series are excluded or awaiting checks</h2><p>Red = a recorded failure. Orange = evidence still needed. One field can have several problems, so reason counts overlap.</p><p class="small">These are additional-source variants and the selected provisional sentiment cohort. They may overlap the confirmed registry and must not be added to it. Only fields with recorded numeric observations are counted; empty numeric slots are excluded. This is the saved audit window, 1 October 2024–30 September 2026, not a new audit of every current file.</p>'+''.join(parts)+'</section>'


def render(data):
    validate(data)
    confirmed,provisional=totals(data)
    rows={row['id']:row for row in data['types']}
    primary=[];review=[];grids=[]
    for identifier,label in LABELS.items():
        row=rows[identifier]
        grid=waffle(row['confirmed_series'])
        if row['provisional_series']:grid+=waffle(row['provisional_series'],True)
        grids.append('<div class="waffle-row"><strong>'+html.escape(label)+'</strong><div>'+grid+'</div></div>')
        cells=[html.escape(label),f"{row['confirmed_series']:,}",f"{row['confirmed_units']:,}",f"{row['provisional_series']:,}"]
        primary.append('<tr><th scope="row">'+cells[0]+'</th><td class="confirmed">'+cells[1]+'</td><td>'+cells[2]+'</td><td class="provisional">'+cells[3]+'</td><td><a href="#issues-'+identifier+'">See problems</a></td></tr>')
        review.append('<tr><th scope="row">'+html.escape(label)+'</th>'+''.join('<td>'+f'{row[key]:,}'+'</td>' for key in ['additional_failed','additional_review','unvalidated_groups'])+'</tr>')
    audit=html.escape(datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00')).strftime('%d %B %Y'))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="1800"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Kuina · Dataset quality</title><style>
.failed{color:#a12b35;background:#fff0f1}.review{color:#925c0b;background:#fff5e7}.issue-type{padding:16px 0;border-top:1px solid var(--line);scroll-margin-top:20px}.issue-type:target{outline:2px solid #27648b;outline-offset:4px}
:root{color-scheme:light;--ink:#18283a;--muted:#586c7c;--line:#dbe2e9}*{box-sizing:border-box}body{font:15px system-ui,sans-serif;color:var(--ink);background:#f2f5f7;margin:0}main{max-width:1100px;margin:auto;padding:32px 22px}h1{margin:0;font-size:32px;letter-spacing:-1px}h2{font-size:20px}p{line-height:1.6;color:var(--muted)}.cards{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px 24px;flex:1;min-width:220px}.card strong{display:block;font-size:36px;color:#216f57}.card.orange strong{color:#9a5f0d}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:20px}.wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:11px 12px;text-align:right}th:first-child{text-align:left}thead th{font-size:12px;color:var(--muted)}.confirmed{background:#eff8f3}.provisional{background:#fff6e8}.small{font-size:12px}.tag{font:11px ui-monospace,monospace;letter-spacing:1.5px;text-transform:uppercase;color:#2d755f}details summary{cursor:pointer;font-weight:600}a{color:#27648b}footer{margin:24px 0}.waffle-row{display:grid;grid-template-columns:180px 1fr;gap:18px;padding:12px 0;border-bottom:1px solid var(--line)}.waffle-row svg{display:block;width:100%;max-width:640px;max-height:520px}.confirmed-square{fill:#25826b}.provisional-square{fill:#dc8d27}@media(max-width:600px){.waffle-row{grid-template-columns:1fr;gap:6px}}</style></head><body><main>
<div class="tag">Kuina · Public quality counts</div><h1>Which series meet our requirements?</h1>
<p>Last verified audit: <strong>'''+audit+'''</strong>. This page refreshes every 30 minutes. Daily publishing checks for a newer verified summary; it does not run a new data audit.</p>
<div class="cards"><div class="card"><strong>'''+f'{confirmed:,}'+'''</strong>Confirmed numeric series</div><div class="card orange"><strong>'''+f'{provisional:,}'+'''</strong>Provisional sentiment signals · not included in confirmed total</div></div>
<section class="panel"><h2>Confirmed counts by dataset type</h2><p class="small">One numeric field is one series. For example, open, high, low and close count separately. Zero means none confirmed, not that no data exist.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Confirmed series</th><th>Confirmed assets / accounts</th><th>Provisional signals</th><th>Why others are excluded</th></tr></thead><tbody>'''+''.join(primary)+'''</tbody></table></div></section>
<section class="panel"><h2>One square per series</h2><p class="small">Green = confirmed. Orange = provisional and excluded from the confirmed total. Squares represent counts only; no observations are embedded.</p>'''+''.join(grids)+'''</section><details class="panel"><summary>Other available data and remaining checks</summary><p class="small">These counts concern the additional-source audit. They are separate source variants and may overlap the confirmed registry; do not add them together. Fields without numeric observations are excluded. Groups without a validated table can be support snapshots or unresolved schemas.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Failed measured checks</th><th>Needs further checks</th><th>No validated table</th></tr></thead><tbody>'''+''.join(review)+'''</tbody></table></div><p class="small">Unresolved checks include market calendars, price construction and adjustment, historical release timing, revisions and source formats. The 129 provisional sentiment signals have supported derived grids; scrape completeness and processing availability are not fully certified.</p></details>
'''+problem_section(data)+'''<details class="panel"><summary>Requirements and update policy</summary><p>Financial prices need at least two calendar years of actual history, hourly or finer native observations (15 minutes preferred), valid values and no unexplained empty expected hourly blocks under the correct calendar. Context retains its own native cadence and needs coverage and availability evidence.</p><p>No price observations, sentiment values, timestamp arrays, credentials, participant information or delegation tasks are published here. The data and task hub remain in private project storage.</p><p>Counts only change after an approved audit snapshot is published. If no new audit is available, the last-audit date stays unchanged.</p></details><footer class="small"><a href="summary.json">Download public counts metadata</a></footer></main></body></html>'''


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

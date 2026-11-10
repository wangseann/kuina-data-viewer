"""Build a public dashboard from an explicit counts-only metadata schema."""
import argparse
from datetime import datetime,timezone
import html
import json
from pathlib import Path
from failure_codes import FAILURE_COLOURS, REASON_BITS, visible_counts

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

FULL_COUNTS={'excluded_missing_evidence', 'source_failures', 'confirmed_units', 'excluded_series', 'excluded_measured', 'confirmed_series'}
FULL_ISSUES={'inconsistent_ohlc':'Inconsistent open / high / low / close candles','ohlc_check_missing':'Ohlc could not be established','not_source_observations': 'Source is not established as historical observations', 'input_identity_unverified': 'Source bytes / identity not verified', 'series_type_unknown': 'Price versus contextual variable is not established', 'no_valid_observations': 'No valid timed numerical observations', 'no_window_data': 'No valid observations in the selected test window', 'invalid_values': 'Invalid numerical observations in the selected test window', 'invalid_times': 'Unparseable observation timestamps', 'conflicting_duplicates': 'Different values occur at the same series timestamp', 'source_parse_error': 'At least one input could not be completely parsed', 'aggregation_unverified': 'Raw events lack a verified forecast-feature aggregation rule', 'score_probability_invalid': 'Sentiment probabilities or score formula failed validation', 'grid_alignment_invalid': 'Timestamps disagree with the declared observation grid', 'short_history': 'Less than two calendar years of valid history', 'calendar_unverified': 'Historical trading / reporting calendar not verified', 'coarse_resolution': 'Financial prices are coarser than hourly', 'cadence_unknown': 'Native observation cadence not established', 'missing_months': 'Financial prices are absent from at least one test-window month', 'price_definition_unverified': 'Price construction, side or adjustment not established', 'availability_unverified': 'Historical publication timing / revision evidence missing', 'collection_completeness_unverified': 'Raw-event collection completeness not established', 'completeness_unverified': 'Completeness cannot be established with the available evidence', 'hourly_gaps': 'At least one expected hourly block is empty', 'long_gaps': 'A within-session gap exceeds the accepted hourly limit', 'context_gaps': 'At least one expected contextual reporting period is missing', 'scrape_completeness': 'Account-level tweet collection completeness is not established', 'causal_processing_unverified': 'Feature availability and causal processing lineage not established', 'numeric_observations_check_missing': 'Numeric observations could not be established', 'window_observations_check_missing': 'Window observations could not be established', 'value_check_missing': 'Value could not be established', 'timestamp_check_missing': 'Timestamp could not be established', 'duplicate_check_missing': 'Duplicate could not be established', 'source_parse_check_missing': 'Source parse could not be established', 'sentiment_score_check_missing': 'Sentiment score could not be established', 'grid_alignment_check_missing': 'Grid alignment could not be established', 'history_span_check_missing': 'History span could not be established', 'window_months_check_missing': 'Window months could not be established'}


def validate(data):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema'] not in (1,2,3,4):
        raise ValueError('Only the counts-only schema is accepted')
    required={'schema','audit_utc','types'}
    if data['schema']==4:required|={'assessment_utc','requirements'}
    if set(data)!=required:
        raise ValueError('Only the counts-only schema is accepted')
    if not isinstance(data['audit_utc'],str):
        raise ValueError('Audit time must be an ISO timestamp')
    when=datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00'))
    if when.tzinfo is None:
        raise ValueError('Audit time must include a timezone')
    if data['schema']==4:
        requirements=data['requirements']
        if not isinstance(requirements,dict)or set(requirements)!={'max_native_seconds','min_history_years'}or any(type(v)is not int for v in requirements.values())or requirements!={'max_native_seconds':900,'min_history_years':2}:
            raise ValueError('Unexpected quality profile')
        if not isinstance(data['assessment_utc'],str):raise ValueError('Assessment time must be an ISO timestamp')
        assessment=datetime.fromisoformat(data['assessment_utc'].replace('Z','+00:00'))
        if assessment.tzinfo is None or assessment<when:raise ValueError('Assessment cannot precede the source audit')
    if not isinstance(data['types'],list) or len(data['types'])!=len(IDS):
        raise ValueError('Every dataset type must occur exactly once')
    seen=set()
    for row in data['types']:
        fields=(FULL_COUNTS|{'id','issues'})if data['schema']in (3,4) else COUNTS|{'id'}
        if data['schema']==4:fields|={'failure_masks'}
        if data['schema']==2:fields=fields|{'issues'}
        if not isinstance(row,dict) or set(row)!=fields or not isinstance(row['id'],str) or row['id'] not in IDS or row['id'] in seen:
            raise ValueError('Unexpected fields or duplicate dataset type')
        seen.add(row['id'])
        if any(type(row[key]) is not int or not 0<=row[key]<=10**9 for key in (FULL_COUNTS if data['schema']in (3,4) else COUNTS)):
            raise ValueError('Counts must be nonnegative integers')
        if row['confirmed_units']>row['confirmed_series']:
            raise ValueError('Confirmed units cannot exceed numeric series')
        if data['schema']in (3,4):
            if row['excluded_measured']+row['excluded_missing_evidence']!=row['excluded_series']:
                raise ValueError('Excluded totals must reconcile exactly')
            if not isinstance(row['issues'],list)or len(row['issues'])>len(FULL_ISSUES):
                raise ValueError('Only aggregate issue counts are accepted')
            issue_ids=set()
            for issue in row['issues']:
                if not isinstance(issue,dict)or set(issue)!={'id','count'}or not isinstance(issue['id'],str)or issue['id']not in FULL_ISSUES or issue['id']in issue_ids:
                    raise ValueError('Unexpected or duplicate issue ID')
                if type(issue['count'])is not int or not 0<issue['count']<=row['excluded_series']:
                    raise ValueError('Issue counts must refer to excluded fields')
                issue_ids.add(issue['id'])
            if row['excluded_series']and sum(i['count']for i in row['issues'])<row['excluded_series']:
                raise ValueError('Every excluded series needs a failed requirement')
        if data['schema']==4:
            masks=row['failure_masks']
            if not isinstance(masks,list)or len(masks)>15:raise ValueError('Only aggregate failure combinations are accepted')
            seen_masks=set()
            for item in masks:
                if not isinstance(item,dict)or set(item)!={'mask','count'}or type(item['mask'])is not int or not 1<=item['mask']<=15 or item['mask']in seen_masks:
                    raise ValueError('Unexpected failure combination')
                if type(item['count'])is not int or not 0<item['count']<=row['excluded_series']:raise ValueError('Invalid failure-combination count')
                seen_masks.add(item['mask'])
            if sum(item['count']for item in masks)!=row['excluded_series']:raise ValueError('Failure combinations must cover each excluded series once')
            for bit in [1,2,4,8]:
                union=sum(item['count']for item in masks if item['mask']&bit)
                counts=[issue['count']for issue in row['issues']if REASON_BITS.get(issue['id'],8)==bit]
                if not max(counts,default=0)<=union<=sum(counts):raise ValueError('Failure colours disagree with the reason counts')
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
            sum(row.get('provisional_series',0) for row in data['types']))


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
    if data['schema']in (3,4):return render_full(data)
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


def failed_waffle(count):
    if not count:return '<span class="small">0 excluded</span>'
    shown=min(count,4000);columns=160;pitch=4;height=((shown+columns-1)//columns)*pitch
    squares=''.join(f'<rect class="square failed-square" x="{i%columns*pitch}" y="{i//columns*pitch}" width="3" height="3"/>'for i in range(shown))
    note=f'<p class="small">First {shown:,} of {count:,} excluded series shown; each square still represents one series.</p>'if shown<count else ''
    return f'<svg viewBox="0 0 640 {height}" role="img" aria-label="{count:,} excluded numeric series">{squares}</svg>'+note



def colour_styles():
    return ''.join('.failure-'+str(bit)+'{color:'+colour+';background:'+colour+'15}'for bit,(_,colour)in FAILURE_COLOURS.items())


def failure_waffle(buckets, identifier):
    if not buckets:return '<span class="small">0 excluded</span>'
    counts=visible_counts(buckets)
    total=sum(item['count']for item in buckets)
    shown=sum(counts.values());definitions=[];squares=[];position=0
    for mask,count in sorted(counts.items()):
        colours=[colour for bit,(_,colour)in FAILURE_COLOURS.items()if mask&bit]
        label='; '.join(label for bit,(label,_)in FAILURE_COLOURS.items()if mask&bit)
        gradient='failure-mask-'+identifier+'-'+str(mask)
        stops=[]
        for index,colour in enumerate(colours):
            stops.append('<stop offset="'+str(index/len(colours)*100)+'%" stop-color="'+colour+'"/>')
            stops.append('<stop offset="'+str((index+1)/len(colours)*100)+'%" stop-color="'+colour+'"/>')
        definitions.append('<linearGradient id="'+gradient+'">'+''.join(stops)+'</linearGradient>')
        for _ in range(count):
            squares.append(f'<rect class="square failed-square mask-{mask}" x="{position%160*4}" y="{position//160*4}" width="3" height="3" style="fill:url(#{gradient})"><title>'+html.escape(label)+'</title></rect>')
            position+=1
    note=f'<p class="small">{shown:,} of {total:,} excluded series shown. Colour combinations are sampled proportionally; every square represents one series. Exact totals are in the tables.</p>'if shown<total else ''
    return f'<svg viewBox="0 0 640 {((shown+159)//160)*4}" role="img" aria-label="{total:,} excluded series by failure combination"><defs>'+''.join(definitions)+'</defs>'+''.join(squares)+'</svg>'+note


def render_full(data):
    coloured=data['schema']==4
    descriptions=dict(FULL_ISSUES)
    if coloured:
        descriptions.update(coarse_resolution='Native observations are coarser than 15 minutes',long_gaps='A within-session gap exceeds the 15-minute observation requirement')
    confirmed=sum(r['confirmed_series']for r in data['types']);excluded=sum(r['excluded_series']for r in data['types'])
    rows={r['id']:r for r in data['types']};table=[];grids=[];problems=[]
    for identifier,label in LABELS.items():
        row=rows[identifier]
        cells=[html.escape(label)]+[f"{row[k]:,}"for k in ['confirmed_series','confirmed_units','excluded_series','excluded_measured','excluded_missing_evidence','source_failures']]
        table.append('<tr><th scope="row">'+cells[0]+'</th>'+''.join('<td>'+c+'</td>'for c in cells[1:])+'<td><a href="#issues-'+identifier+'">Reasons</a></td></tr>')
        grids.append('<section><h3>'+html.escape(label)+f" · {row['confirmed_series']:,} eligible · {row['excluded_series']:,} excluded</h3>"+waffle(row['confirmed_series'])+(failure_waffle(row['failure_masks'],identifier)if coloured else failed_waffle(row['excluded_series']))+'</section>')
        reasons=''.join('<tr'+(' class="failure-'+str(REASON_BITS.get(i['id'],8))+'"'if coloured else '')+'><th scope="row">'+html.escape(descriptions[i['id']])+'</th><td>'+f"{i['count']:,}"+'</td></tr>'for i in sorted(row['issues'],key=lambda i:(-i['count'],i['id'])))
        if not reasons:reasons='<tr><td colspan="2">No excluded numerical series identified for this type.</td></tr>'
        source_note=f"<p>{row['source_failures']:,} source groups did not yield an identified historical time/value table. Their numerical-series count is unknown; they are excluded separately.</p>"if row['source_failures']else ''
        problems.append('<details class="panel" id="issues-'+identifier+'"><summary>'+html.escape(label)+'</summary><table><thead><tr><th>Failed requirement</th><th>Affected series</th></tr></thead><tbody>'+reasons+'</tbody></table>'+source_note+'</details>')
    legend='<span class="legend-green">Green = eligible.</span> <span class="legend-red">Red = excluded, including missing mandatory evidence.</span>'
    requirement='Financial prices require at least two calendar years of actual history, hourly or finer native data (15 minutes preferred), valid timestamps and values, a verified price definition and no unexplained empty expected hourly blocks under the correct historical calendar.'
    if coloured:
        legend='<span class="legend-green">Green = eligible.</span> '+ ' '.join('<span style="color:'+colour+'">'+html.escape(label)+'.</span>'for label,colour in FAILURE_COLOURS.values())+' Several colours in one square mean that series failed several requirements.'
        requirement='Regular time series require native observations every 15 minutes or finer and at least two calendar years of valid history. Hourly data now fail the resolution check. Financial observation gaps must also stay within the 15-minute limit under the verified trading calendar.'
    audit=html.escape(datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00')).astimezone(timezone.utc).strftime('%d %B %Y, %H:%M UTC'))
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="1800"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Kuina · Full dataset eligibility</title><style>body{font:15px system-ui;color:#1b3040;background:#f4f7f9;margin:32px auto;max-width:1250px;padding:0 20px}p{line-height:1.6;color:#536878}h1{font-size:32px}.cards{display:flex;gap:20px;margin:24px 0}.card,.panel{background:white;border:1px solid #dce4eb;border-radius:12px;padding:20px}.card{flex:1}.card strong{display:block;font-size:34px;color:#207455}.card.red strong{color:#b33440}.panel{margin:18px 0;scroll-margin-top:20px}.panel:target{outline:2px solid #27648b}.wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:11px;border-bottom:1px solid #dce4eb;text-align:right}th:first-child{text-align:left}a{color:#17658b}.small{font-size:12px}svg{display:block;width:100%;max-width:640px;max-height:520px}.confirmed-square{fill:#25826b}.failed-square{fill:#cb4554}'+(colour_styles()if coloured else '')+'summary{cursor:pointer;font-weight:600}.legend-green{color:#207455}.legend-red{color:#b33440}@media(max-width:600px){.cards{display:block}.card{margin-bottom:12px}}</style></head><body><main><h1>Which series meet our requirements?</h1><p>Full stored-source audit: <strong>'+audit+'</strong>'+(' · 15-minute assessment: '+html.escape(data['assessment_utc'])if coloured else '')+'. This page refreshes every 30 minutes; daily publishing only checks for a newer verified audit.</p><div class="cards"><div class="card"><strong>'+f'{confirmed:,}'+'</strong>Eligible numeric series</div><div class="card red"><strong>'+f'{excluded:,}'+'</strong>Excluded numeric series</div></div><section class="panel"><h2>Counts by dataset type</h2><p>One numerical field is one series: open, high, low and close count separately. Duplicate versions do not add series. Different sources, quote variants and native intervals remain separate.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Eligible series</th><th>Eligible units</th><th>Excluded series</th><th>Measured failure</th><th>Required evidence missing only</th><th>Groups without a validated series table</th><th>Details</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div><p class="small">Measured failure and evidence-only exclusions sum to the excluded total. A measured failure may also have missing evidence. Source groups with unknown series counts are separate.</p></section><section class="panel"><h2>One square per identified numeric series</h2><p>'+legend+' No unverified series is included in the eligible total.</p>'+''.join(grids)+'</section><h2>Exact failed requirements by dataset type</h2><p>One series can fail several requirements, so reason counts overlap. Required evidence missing is an exclusion, even when observed values look complete. The private Kuina report lists each series and its supporting measurements.</p>'+''.join(problems)+'<section class="panel"><h2>Requirements</h2><p>'+requirement+'</p><p>'+('Contextual predictors must also satisfy the 15-minute resolution limit; historical reporting availability and revision evidence remain required.'if coloured else 'Contextual predictors retain their native cadence and require reporting coverage, historical availability and revision evidence.')+' Tweets and derived signals also require account collection completeness and causal processing lineage.</p><p>Audit window: 1 October 2024–30 September 2026. Dataset types follow the storage inventory; GDELT tone/GCAM attributes belong to GDELT. The public page contains aggregate counts only. Observations, identifiers, credentials and delegation tasks remain private.</p></section><p><a href="summary.json">Download public counts metadata</a></p></main></body></html>'


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

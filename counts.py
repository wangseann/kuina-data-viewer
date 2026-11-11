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


PLAIN_ISSUES = {'inconsistent_ohlc': ('Price candle values contradict each other',
                       'The opening, highest, lowest or closing price does not fit the others; for '
                       'example, the highest price is below the closing price.'),
 'ohlc_check_missing': ('The price candle consistency check is missing',
                        'We have not established whether each candle has sensible opening, highest, '
                        'lowest and closing prices.'),
 'not_source_observations': ('We cannot confirm these are recorded historical values',
                             'The files may contain predictions, summaries or supporting information '
                             'rather than measurements recorded for that time.'),
 'input_identity_unverified': ('File-version check unfinished',
                               'The audit has not tied this result to a verified input fingerprint. Check the existing file '
                               'inventory and hashes, then rerun affected checks if necessary. New observations are not '
                               'required for this check.'),
 'series_type_unknown': ('We do not know what kind of value this is',
                         'We cannot establish whether this is a market price or another predictor, such '
                         'as a sentiment score or economic indicator.'),
 'no_valid_observations': ('No usable numbers with dates remain',
                           'The series has no observations that can be used after checking its numbers '
                           'and dates.'),
 'no_window_data': ('No usable data fall inside our test dates',
                    'We found no usable observations from 1 October 2024 through 30 September 2026, '
                    'even if data exist outside those dates.'),
 'invalid_values': ('Some recorded numbers are invalid',
                    'Some entries cannot be used as numbers, such as infinity or an unreadable number.'),
 'invalid_times': ('Some dates or times cannot be read',
                   'One or more observations have timestamps the audit could not turn into a usable '
                   'date and time.'),
 'conflicting_duplicates': ('The same time has different recorded values',
                            'More than one value exists for the same series at the same time, and the '
                            'conflict needs to be resolved.'),
 'source_parse_error': ('Some source files could not be fully read',
                        'The audit could not read the complete contents of at least one input file, so '
                        'the result may be incomplete.'),
 'aggregation_unverified': ('Event-to-series calculation not checked',
                            'The audit has not verified how individual events become regular predictor values. Inspect '
                            'the existing aggregation code, interval boundaries and timestamps before treating this as a '
                            'request for new data.'),
 'score_probability_invalid': ('Sentiment scores failed a maths check',
                               'The saved scores or probabilities do not meet the scoring rules used by '
                               'the audit.'),
 'grid_alignment_invalid': ('Recorded times do not match the stated schedule',
                            'The timestamps do not line up with the regular intervals the dataset '
                            'claims to use.'),
 'short_history': ('Less than two years of usable history',
                   'The first and last valid observations do not span two full calendar years. This '
                   'check is separate from checks for gaps inside that span.'),
 'calendar_unverified': ('Market or reporting schedule not checked',
                         'The audit has not matched this series to its opening hours, holidays or reporting schedule. '
                         'Check the existing source and exchange information before deciding whether an empty period '
                         'is a gap.'),
 'coarse_resolution': ('Values are recorded less often than every 15 minutes',
                       'The original data are hourly, daily or otherwise too far apart. Adding copied '
                       'or interpolated values would not make them qualify.'),
 'cadence_unknown': ('Recording interval not established by the audit',
                     'Check the existing timestamps and interval labels to establish how often values were '
                     'originally recorded. This flag does not establish that the data are too coarse.'),
 'missing_months': ('At least one test month has no price data',
                    'One or more months inside our test dates contain no valid prices for this series.'),
 'price_definition_unverified': ('Price meaning not checked',
                                 'Inspect the existing column names and source metadata for bid, ask or trade prices, candle '
                                 'construction, and adjustment for splits or dividends. Consult the provider description if '
                                 'those details are absent. This flag is not a finding that the prices are wrong.'),
 'availability_unverified': ('Historical release timing not checked',
                             'The audit did not establish when each value first became available or which revision it '
                             'contains. An observation date alone cannot answer that: a January figure published in March '
                             'was unavailable for a January forecast. Inspect stored publication, release and collection '
                             'timestamps first.'),
 'collection_completeness_unverified': ('Event collection not cross-checked',
                                        'The audit has not established whether the stored events cover the intended collection. '
                                        'Check existing collection logs and source coverage; the observed events alone cannot reveal '
                                        'every missed event.'),
 'completeness_unverified': ('Gap check unfinished',
                             'The audit could not complete the gap test using a verified schedule and coverage counts. '
                             'This flag does not establish that observations are missing. Inspect the existing timestamps '
                             'and schedule first.'),
 'hourly_gaps': ('Some expected hours have no data',
                 'The earlier audit measured at least one empty hour when observations should have '
                 'existed. That also fails the current 15-minute requirement.'),
 'long_gaps': ('A gap between observations is longer than 15 minutes',
               'Within the checked market schedule, some consecutive observations are more than 15 '
               'minutes apart.'),
 'context_gaps': ('Some expected reports or predictor values are missing',
                  'An observation is missing at a time when the checked reporting schedule says one '
                  'should exist.'),
 'scrape_completeness': ('Account scraping not cross-checked',
                         'Collected tweets alone cannot show which posts were missed. Check the existing scrape logs, '
                         'pagination and account coverage. An empty period is not automatically a scrape failure.'),
 'causal_processing_unverified': ('Signal calculation timing not checked',
                                  'The audit has not verified from the existing calculation code and logs that a signal uses '
                                  'only information available by its timestamp. This requires checking the processing, not '
                                  'automatically collecting more data.'),
 'numeric_observations_check_missing': ('The check for usable numbers is missing',
                                        'The audit has no completed check proving this series contains '
                                        'usable numerical observations.'),
 'window_observations_check_missing': ('The check for data inside our test dates is missing',
                                       'The audit has not established whether usable observations exist '
                                       'from 1 October 2024 through 30 September 2026.'),
 'value_check_missing': ('The check for invalid numbers is missing',
                         'The audit has no completed result showing whether the recorded numbers are '
                         'valid.'),
 'timestamp_check_missing': ('The check for readable dates and times is missing',
                             'The audit has no completed result showing whether observation timestamps '
                             'can be read.'),
 'duplicate_check_missing': ('The check for conflicting values at the same time is missing',
                             'The audit has not established whether duplicate timestamps contain '
                             'different values.'),
 'source_parse_check_missing': ('The check that source files were fully read is missing',
                                'The audit has not established whether all input files could be read '
                                'completely.'),
 'sentiment_score_check_missing': ('The sentiment score calculation check is missing',
                                   'The audit has no completed result showing whether saved sentiment '
                                   'scores follow the intended calculation.'),
 'grid_alignment_check_missing': ('The check that times match the stated schedule is missing',
                                  'The audit has not established whether timestamps line up with the '
                                  'claimed recording intervals.'),
 'history_span_check_missing': ('The two-year history check is missing',
                                'The audit has not established the first and last valid observation '
                                'dates, so two years of history cannot be confirmed.'),
 'window_months_check_missing': ('The check for data in every test month is missing',
                                 'The audit has not established whether prices exist in every month of '
                                 'our test dates.')}


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


GRID_STYLE = """
.series-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(10px,1fr));gap:3px;width:100%;margin:14px 0}
.series-grid .square{display:block;aspect-ratio:1;min-width:0}
.series-grid .confirmed-square{background:#25826b}
.reason-explanation{display:block;font-weight:400;font-size:13px;line-height:1.6;margin-top:5px;max-width:850px;color:#394e60}
"""


def eligible_grid(count):
    if not count:
        return '<p class="small">0 eligible</p>'
    shown = min(count, 20000)
    squares = '<span class="square confirmed-square"></span>' * shown
    note = f'<p class="small">First {shown:,} of {count:,} eligible series shown.</p>' if shown < count else ''
    return f'<div class="series-grid" role="img" aria-label="{count:,} eligible numeric series">' + squares + '</div>' + note


def failure_waffle(buckets, identifier):
    if not buckets:
        return '<p class="small">0 excluded</p>'
    counts = visible_counts(buckets)
    total = sum(item['count'] for item in buckets)
    shown = sum(counts.values())
    squares = []
    for mask, count in sorted(counts.items()):
        colours = [colour for bit, (_, colour) in FAILURE_COLOURS.items() if mask & bit]
        label = '; '.join(label for bit, (label, _) in FAILURE_COLOURS.items() if mask & bit)
        bands = [f'{colour} {index / len(colours) * 100}% {(index + 1) / len(colours) * 100}%' for index, colour in enumerate(colours)]
        background = colours[0] if len(colours) == 1 else 'linear-gradient(90deg,' + ','.join(bands) + ')'
        tile = f'<span class="square failed-square failure-mask-{identifier}-{mask}" style="background:{background}" title="{html.escape(label, quote=True)}"></span>'
        squares.append(tile * count)
    note = f'<p class="small">{shown:,} of {total:,} excluded series shown. Colour combinations are sampled proportionally; every square represents one series. Exact totals are in the tables.</p>' if shown < total else ''
    return f'<div class="series-grid" role="img" aria-label="{total:,} excluded series by failure combination">' + ''.join(squares) + '</div>' + note


def reason_row(issue, coloured):
    identifier = issue['id']
    label = html.escape(FULL_ISSUES[identifier])
    style = ''
    if coloured:
        title, explanation = PLAIN_ISSUES[identifier]
        label = html.escape(title) + '<span class="reason-explanation">' + html.escape(explanation) + '</span>'
        style = ' class="failure-' + str(REASON_BITS.get(identifier, 8)) + '"'
    return '<tr' + style + '><th scope="row">' + label + '</th><td>' + f"{issue['count']:,}" + '</td></tr>'


def render_full(data):
    coloured=data['schema']==4
    confirmed=sum(r['confirmed_series']for r in data['types']);excluded=sum(r['excluded_series']for r in data['types'])
    rows={r['id']:r for r in data['types']};table=[];grids=[];problems=[]
    for identifier,label in LABELS.items():
        row=rows[identifier]
        cells=[html.escape(label)]+[f"{row[k]:,}"for k in ['confirmed_series','confirmed_units','excluded_series','excluded_measured','excluded_missing_evidence','source_failures']]
        table.append('<tr><th scope="row">'+cells[0]+'</th>'+''.join('<td>'+c+'</td>'for c in cells[1:])+'<td><a href="#issues-'+identifier+'">Reasons</a> · <a href="explorer.html#type='+identifier+'">Inspect series</a></td></tr>')
        grids.append('<section><h3>'+html.escape(label)+f" · {row['confirmed_series']:,} eligible · {row['excluded_series']:,} excluded</h3>"+(eligible_grid(row['confirmed_series'])if coloured else waffle(row['confirmed_series']))+(failure_waffle(row['failure_masks'],identifier)if coloured else failed_waffle(row['excluded_series']))+'</section>')
        reasons=''.join(reason_row(issue,coloured)for issue in sorted(row['issues'],key=lambda issue:(-issue['count'],issue['id'])))
        if not reasons:reasons='<tr><td colspan="2">No excluded numerical series identified for this type.</td></tr>'
        source_note=f"<p>{row['source_failures']:,} source groups did not yield an identified historical time/value table. Their numerical-series count is unknown; they are excluded separately.</p>"if row['source_failures']else ''
        problems.append('<details class="panel" id="issues-'+identifier+'"><summary>'+html.escape(label)+'</summary><table><thead><tr><th>Problem or unfinished check</th><th>Affected series</th></tr></thead><tbody>'+reasons+'</tbody></table>'+source_note+'</details>')
    legend='<span class="legend-green">Green = eligible.</span> <span class="legend-red">Red = excluded, including missing mandatory evidence.</span>'
    requirement='Financial prices require at least two calendar years of actual history, hourly or finer native data (15 minutes preferred), valid timestamps and values, a verified price definition and no unexplained empty expected hourly blocks under the correct historical calendar.'
    if coloured:
        legend='<span class="legend-green">Green = eligible.</span> '+ ' '.join('<span style="color:'+colour+'">'+html.escape(label)+'.</span>'for label,colour in FAILURE_COLOURS.values())+' Several colours in one square mean that series failed several requirements.'
        requirement='A series needs original recorded values every 15 minutes or more often and at least two full years of usable history. Hourly data fail this requirement. During times when the market should be open, gaps between financial observations must also stay within 15 minutes.'
    audit=html.escape(datetime.fromisoformat(data['audit_utc'].replace('Z','+00:00')).astimezone(timezone.utc).strftime('%d %B %Y, %H:%M UTC'))
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="1800"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Kuina · Full dataset eligibility</title><style>body{font:15px system-ui;color:#1b3040;background:#f4f7f9;margin:32px auto;max-width:1800px;padding:0 20px}p{line-height:1.6;color:#536878}h1{font-size:32px}.cards{display:flex;gap:20px;margin:24px 0}.card,.panel{background:white;border:1px solid #dce4eb;border-radius:12px;padding:20px}.card{flex:1}.card strong{display:block;font-size:34px;color:#207455}.card.red strong{color:#b33440}.panel{margin:18px 0;scroll-margin-top:20px}.panel:target{outline:2px solid #27648b}.wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:11px;border-bottom:1px solid #dce4eb;text-align:right}th:first-child{text-align:left}a{color:#17658b}.small{font-size:12px}svg{display:block;width:100%;max-width:640px;max-height:520px}.confirmed-square{fill:#25826b}.failed-square{fill:#cb4554}'+(colour_styles()+GRID_STYLE if coloured else '')+'summary{cursor:pointer;font-weight:600}.legend-green{color:#207455}.legend-red{color:#b33440}@media(max-width:600px){.cards{display:block}.card{margin-bottom:12px}}</style></head><body><main><h1>Which series meet our requirements?</h1><p>Full stored-source audit: <strong>'+audit+'</strong>'+(' · 15-minute assessment: '+html.escape(data['assessment_utc'])if coloured else '')+'. This page refreshes every 30 minutes; daily publishing only checks for a newer verified audit.</p><div class="cards"><div class="card"><strong>'+f'{confirmed:,}'+'</strong>Eligible numeric series</div><div class="card red"><strong>'+f'{excluded:,}'+'</strong>Excluded numeric series</div></div><section class="panel"><h2>Counts by dataset type</h2><p>One numerical field is one series: open, high, low and close count separately. Duplicate versions do not add series. Different sources, quote variants and native intervals remain separate.</p><div class="wrap"><table><thead><tr><th>Dataset type</th><th>Eligible series</th><th>Eligible units</th><th>Excluded series</th><th>Known data problem</th><th>Only unfinished checks</th><th>Groups without a validated series table</th><th>Details</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div><p class="small">Known data problems and unfinished-check-only counts sum to the excluded total. A series with a known problem may also have unfinished checks. Source groups with unknown series counts are separate.</p></section><section class="panel"><h2>One square per identified numeric series</h2><p>'+legend+' No unverified series is included in the eligible total.</p>'+''.join(grids)+'</section><h2>Data problems and unfinished audit checks</h2><p>One series can have several flags, so counts overlap. A known data problem is a measured failure, such as hourly data or a gap. An unfinished check means the audit has not established the answer; it is not proof that the series is wrong or missing. The saved eligibility total still excludes unresolved checks. Agents should inspect existing files, metadata and processing code first; an unfinished check alone is not a request to scrape more data.</p>'+''.join(problems)+'<section class="panel"><h2>What the series can tell us</h2><p>Existing timestamps and values can establish history, recording intervals, invalid values and conflicting duplicates. Gap checks also need the correct market or reporting schedule. Forecast-use checks ask a different question: when was a value available, and did its calculation use later information? Existing release timestamps, source descriptions, processing code and collection logs may already answer these questions.</p><h2>Requirements</h2><p>'+requirement+'</p><p>'+('Other predictors, such as sentiment scores and economic indicators, also need values every 15 minutes or more often. We must know when values became available and whether they were later changed.'if coloured else 'Contextual predictors retain their native cadence and require reporting coverage, historical availability and revision evidence.')+' For tweets and calculated signals, we also need proof that collection was complete and the calculation used only information available at that time.</p><p>Audit window: 1 October 2024–30 September 2026. Dataset types follow the storage inventory; GDELT tone/GCAM attributes belong to GDELT. The public page contains aggregate counts only. Observations, identifiers, credentials and delegation tasks remain private.</p></section><p><a href="summary.json">Download public counts metadata</a></p></main></body></html>'


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

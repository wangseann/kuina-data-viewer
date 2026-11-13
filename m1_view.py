"""Validate and render the closed, public, observation-free Dukascopy m1 audit."""
from collections import Counter
from datetime import date, datetime, timedelta
import html
import re

from counts import LABELS
from failure_codes import FAILURE_COLOURS
from series_names import safe_text

TYPES = {'stocks', 'crypto', 'currencies', 'commodities', 'other-markets'}
VARIABLES = {'open', 'high', 'low', 'close', 'volume'}
CHECKS = {
    'source_role': 'Historical source observations not established',
    'input_identity': 'Input file identity not verified', 'series_type': 'Numeric field type not established',
    'numeric_observations': 'Usable numeric observations not established',
    'window_observations': 'Usable observations in the testing window not established',
    'value': 'Invalid values or an unverified value check',
    'timestamp': 'Unreadable timestamps or an unverified timestamp check',
    'timestamp_timezone': 'Timestamp timezone not established',
    'duplicate': 'Conflicting duplicate timestamps', 'source_parse': 'Files could not be fully parsed',
    'grid_alignment': 'Timestamps do not match the native grid',
    'history_span': 'Less than two years of usable history',
    'calendar': 'Trading hours not established',
    'native_cadence': 'Native recording interval does not meet the requirement',
    'required_cadence': 'Recording interval exceeds 15 minutes or is unknown',
    'window_months': 'Months missing from the testing window',
    'price_definition': 'Price side, adjustments or volume units not established',
    'ohlc': 'Open, high, low or close values are inconsistent',
    'completeness': 'Missing periods cannot be verified',
    'hourly_coverage': 'Expected hours have no observations',
    'longest_gap': 'Within-session gaps exceed 15 minutes',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), 'Unexpected public fields')


def count(value, maximum=20000):
    require(type(value) is int and 0 <= value <= maximum, 'Invalid public count')


def validate(data):
    keys(data, ('schema', 'audit_utc', 'window_start', 'window_end_exclusive', 'requirements', 'types'))
    require(data['schema'] == 'kuina-m1-audit-public-v1', 'Unsupported m1 schema')
    try:
        epoch = datetime.fromisoformat(data['audit_utc'].replace('Z', '+00:00'))
        require(epoch.utcoffset() == timedelta(0), 'Audit epoch must declare UTC')
        start, end = date.fromisoformat(data['window_start']), date.fromisoformat(data['window_end_exclusive'])
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('Invalid m1 audit dates') from error
    require((start.isoformat(), end.isoformat()) == ('2024-10-01', '2026-10-01'), 'Audit-window drift')
    keys(data['requirements'], ('max_native_seconds', 'min_history_years'))
    require(data['requirements'] == dict(max_native_seconds=900, min_history_years=2)
            and all(type(value) is int for value in data['requirements'].values()), 'Quality-profile drift')
    require(isinstance(data['types'], list) and 0 < len(data['types']) <= len(TYPES), 'Invalid dataset types')
    seen_types, seen_ids = set(), set()
    for group in data['types']:
        keys(group, ('id', 'instrument_count', 'series_count', 'eligible_count', 'failed_count', 'check_failures', 'series'))
        category = group['id']
        require(isinstance(category, str) and category in TYPES and category not in seen_types, 'Unknown or duplicate type')
        seen_types.add(category)
        for field in ('instrument_count', 'series_count', 'eligible_count', 'failed_count'):
            count(group[field])
        require(group['series_count'] == group['eligible_count'] + group['failed_count'], 'Outcome totals differ')
        require(isinstance(group['series'], list) and len(group['series']) == group['series_count'], 'Series count differs')
        require(isinstance(group['check_failures'], list) and len(group['check_failures']) <= len(CHECKS), 'Invalid checks')
        seen_checks = set()
        for check in group['check_failures']:
            keys(check, ('id', 'count'))
            require(isinstance(check['id'], str) and check['id'] in CHECKS and check['id'] not in seen_checks, 'Unknown or duplicate check')
            seen_checks.add(check['id'])
            count(check['count'], group['failed_count'])
            require(check['count'] > 0, 'Empty failure count')
        require(sum(check['count'] for check in group['check_failures']) >= group['failed_count'], 'Failed series lack check accounting')
        fields, eligible = Counter(), 0
        for record in group['series']:
            keys(record, ('id', 'label', 'variable', 'source', 'native_seconds', 'mask'))
            identifier = record['id']
            require(isinstance(identifier, str) and re.fullmatch('[0-9a-f]{64}', identifier)
                    and identifier not in seen_ids, 'Invalid or duplicate series hash')
            seen_ids.add(identifier)
            require(len(seen_ids) <= 20000, 'Series publication bound exceeded')
            require(safe_text(record['label'], 400), 'Unsafe public name')
            require(isinstance(record['variable'], str) and record['variable'] in VARIABLES, 'Unknown numeric field')
            fields[record['variable']] += 1
            require(record['source'] == 'Dukascopy bank CSV', 'Unknown public provider')
            require(type(record['native_seconds']) is int and record['native_seconds'] == 60, 'Expected native m1 interval')
            count(record['mask'], 15)
            eligible += record['mask'] == 0
        require(eligible == group['eligible_count'], 'Masks differ from outcomes')
        require(all(fields[field] == group['instrument_count'] for field in VARIABLES), 'Incomplete OHLCV membership')
    return data


def tile(record):
    mask = record['mask']
    colours = [colour for bit, (_, colour) in FAILURE_COLOURS.items() if mask & bit]
    if not colours:
        background = '#25826b'
        outcome = 'Eligible'
    else:
        stops = ','.join(f'{colour} {index * 100 / len(colours):g}% {(index + 1) * 100 / len(colours):g}%'
                         for index, colour in enumerate(colours))
        background = colours[0] if len(colours) == 1 else f'linear-gradient(135deg,{stops})'
        outcome = 'Excluded: ' + '; '.join(label for bit, (label, _) in FAILURE_COLOURS.items() if mask & bit)
    label = html.escape(f"{record['label']} · {record['variable']}\nSource: {record['source']}\nNative interval: 60 seconds\n{outcome}", quote=True)
    return f'<span class="tile" tabindex="0" title="{label}" aria-label="{label}" style="background:{background}"></span>'


def render(data=None):
    """Render only an explicitly supplied verified snapshot, or the unpublished state."""
    content = '<section><h2>Not yet published</h2><p>The complete native m1 audit has not yet been published. Results will appear here after verification.</p></section>'
    selection_css = ''
    if data is not None:
        validate(data)
        controls, sections = [], []
        for index, group in enumerate(data['types']):
            checked = ' checked' if index == 0 else ''
            title = html.escape(LABELS[group['id']])
            controls.append(f'<input type="radio" name="dataset" id="dataset-{index}"{checked}><label for="dataset-{index}">{title}</label>')
            selection_css += f'#dataset-{index}:checked~.dataset-{index}'+'{display:block}'
            checks = ''.join(f'<tr><th scope="row">{CHECKS[check["id"]]}</th><td>{check["count"]:,}</td></tr>' for check in group['check_failures'])
            table = '<table><caption>Results needing attention</caption><thead><tr><th>Result</th><th>Series</th></tr></thead><tbody>'+checks+'</tbody></table>' if checks else '<p>No results need attention.</p>'
            sections.append(f'<section class="dataset dataset-{index}"><h2>{title}</h2><p>{group["instrument_count"]:,} instruments · {group["series_count"]:,} numeric series · {group["eligible_count"]:,} eligible · {group["failed_count"]:,} excluded</p><div class="tiles">'+''.join(tile(record) for record in group['series'])+'</div>'+table+'</section>')
        explanation = ('<p>Every series listed here was checked. Where saved files do not identify trading hours, '
                       'bid versus ask prices, adjustments or volume units, those checks remain unverified. '
                       'This alone does not show that prices are wrong.</p>')
        content = '<p>Native m1 audit: <strong>'+html.escape(data['audit_utc'])+'</strong>. This is the Dukascopy m1 audit date; the full stored-source audit retains its separate date.</p>'+explanation+'<p>Select a dataset type:</p>'+''.join(controls)+''.join(sections)
    legend = '<span class="legend" style="background:#25826b"></span> Eligible · '+ ' · '.join(f'<span class="legend" style="background:{colour}"></span> {label}' for label, colour in FAILURE_COLOURS.values())
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Kuina · Dukascopy m1 audit</title><style>
body{font:16px system-ui,sans-serif;background:#f4f7f9;color:#1b3040;margin:0}main{max-width:1200px;margin:auto;padding:30px 20px}p{line-height:1.6;color:#536878}a{color:#17658b}h1{font-size:32px}section{background:white;border:1px solid #dce4eb;border-radius:12px;padding:22px;margin:20px 0}.dataset{display:none}.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(32px,1fr));gap:6px;margin:22px 0}.tile{display:block;aspect-ratio:1;border-radius:3px}.tile:focus{outline:3px solid #102f49;outline-offset:2px}.legend{display:inline-block;width:14px;height:14px;vertical-align:middle}label{display:inline-block;padding:10px 12px;margin:6px 12px 6px 0;border-radius:8px;background:white;cursor:pointer}input:checked+label{background:#dcebf3;color:#174c6a}table{border-collapse:collapse;width:100%;text-align:left}caption{text-align:left;font-weight:600;margin:20px 0 10px}th,td{padding:12px;border-bottom:1px solid #dce4eb}td{text-align:right}@media(max-width:600px){main{padding:20px 12px}section{padding:14px}.tiles{grid-template-columns:repeat(auto-fill,minmax(28px,1fr))}}
'''+selection_css+'</style></head><body><main><nav><a href="index.html">Quality counts</a> · <a href="m1.html" aria-current="page">Dukascopy m1 audit</a> · <a href="tasks.html">Agent tasks</a></nav><h1>Every Dukascopy m1 series</h1><p>Each square is one numerical field. Hover or focus a square for its name, field, provider, interval and result. Multiple colours preserve combined failure categories.</p><p>'+legend+'</p><p>Requirements: at least two years of actual history, native intervals of 15 minutes or finer, and all mandatory checks passed. Audit window: 1 October 2024–30 September 2026. Check counts overlap when a series fails several checks.</p>'+content+'</main></body></html>'

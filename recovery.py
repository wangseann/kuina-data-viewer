"""Reviewed source-frequency limits and the active work-catalogue exclusion.

The original batches remain immutable history. These exact source-pure partitions
must not be offered as new assignments. No data eligibility is changed here.
"""
from copy import deepcopy
import html

TOTAL = 4_719_383
IMPOSSIBLE = 4_182_499
EXCLUDED_BATCHES = 13_543
GENERATION = 'e5a51c332a2c4cfba8ef258727ab2f90cb70e459addff7e7c0c64d647b65918d'
AUDIT_UTC = '2026-11-09T14:39:02.217131+00:00'
PROOF_SHA256 = '27cbb61377259f99603d679d1c54ab0f66984d8c7f41c22e1365035e4af14c5f'
PARTITIONS = (
    ('unique-trade-comtrade-statistical-7e4192e4cc9c5661-', 'UN Comtrade', 'Monthly', 2_423_291),
    ('unique-commodities-fao-statistical-0c42364d8b264d54-', 'FAOSTAT', 'Annual / monthly', 972_308),
    ('unique-derivatives-cftc-statistical-5636289b25ae1c25-', 'CFTC COT', 'Weekly', 786_900),
)


def retired_batch(batch_id):
    return isinstance(batch_id, str) and any(batch_id.startswith(row[0]) for row in PARTITIONS)


def retire_catalogue(catalogue, ledger):
    """Preserve generation, live assignments, definition hashes and receipts."""
    if catalogue['generation'] != GENERATION:
        raise ValueError('Source-limit policy requires its reviewed catalogue generation')
    removed = [r for r in catalogue['batches'] if retired_batch(r['id'])]
    if any(r['id'] in ledger['assignments'] for r in removed):
        raise ValueError('An unrecoverable batch has an assignment; coordinator reconciliation required')
    value = deepcopy(catalogue)
    value['batches'] = [r for r in value['batches'] if not retired_batch(r['id'])]
    legacy = value.setdefault('legacy_definitions', [])
    known = {r['batch_id'] for r in legacy}
    for row in removed:
        if row['id'] in known:
            raise ValueError('Repeated retired batch definition')
        legacy.append(dict(batch_id=row['id'], definition_sha256=row['definition_sha256']))
        known.add(row['id'])
    statistics = dict(batches=len(removed), targets=sum(r['target_count'] for r in removed),
                      series=sum(r['series_count'] for r in removed), remaining_batches=len(value['batches']))
    return value, statistics


def panel(counts):
    """Numeric-series units only; candidates are never called confirmed rescues."""
    total = sum(r['confirmed_series'] + r['excluded_series'] for r in counts['types'])
    if counts['schema'] != 4 or total != TOTAL or counts['audit_utc'] != AUDIT_UTC:
        return ''
    eligible = sum(r['confirmed_series'] for r in counts['types'])
    unresolved = total - eligible - IMPOSSIBLE
    if unresolved < 0:
        raise ValueError('Recovery classification does not reconcile with the audit')
    rows = ''.join('<tr><th scope="row">'+html.escape(name)+'</th><td>'+cadence+'</td><td>'+f'{number:,}'+'</td></tr>'
                   for _, name, cadence, number in PARTITIONS)
    return ('<section class="panel" id="recovery"><h2>Recovery status · numeric series</h2>'
            '<div class="cards"><div class="card"><strong>'+f'{eligible:,}'+'</strong>Eligible now</div>'
            '<div class="card red"><strong>'+f'{IMPOSSIBLE:,}'+'</strong>Confirmed unrecoverable under the current requirements</div>'
            '<div class="card"><strong>'+f'{unresolved:,}'+'</strong>Other ineligible series · outcome unresolved</div></div>'
            '<p>The same monthly, annual or weekly variable cannot become native 15-minute observations. '
            'These '+f'{EXCLUDED_BATCHES:,}'+' batches are excluded from the current assignment pool.</p>'
            '<table><thead><tr><th>Exact source product</th><th>Native interval</th><th>Unrecoverable series</th></tr></thead>'
            '<tbody>'+rows+'</tbody></table>'
            '<p class="small">This is a confirmed minimum. Other ineligible series are not automatically recoverable. '
            'Original data and assignment history are retained.</p></section>'
            '<section class="panel" id="confirmed-rescuable"><h2>Confirmed rescue plans awaiting completion</h2>'
            '<p><strong>0 recorded in this assessment.</strong> Unverified repair candidates are not counted as confirmed rescues.</p>'
            '<p><a href="sources.html">Find new data by market and sector →</a></p></section>')


def work_notice():
    return ('<section class="panel" id="recovery"><h2>New data acquisition</h2>'
            '<p><a href="sources.html">Market / sector source-search tracker →</a> · '
            '<a href="index.html#recovery">Unrecoverable series and confirmed rescue plans</a></p>'
            '<p>Confirmed-unrecoverable source batches are excluded. Remaining investigation batches do not guarantee recovery. '
            'Existing assignments are retained; new collection requires source qualification.</p></section>')

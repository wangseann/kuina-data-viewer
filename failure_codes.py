"""Display and reassessment rules for the requested 15-minute quality profile."""

FAILURE_COLOURS = {
    1: ('Missing data / gaps', '#237cb6'),
    2: ('Coarser than 15 minutes', '#e18c1f'),
    4: ('Less than two years', '#8654a8'),
    8: ('Other failed checks / missing evidence', '#7b8795'),
}
REASON_BITS = dict.fromkeys([
    'no_valid_observations', 'no_window_data', 'missing_months',
    'hourly_gaps', 'long_gaps', 'context_gaps',
], 1)
REASON_BITS.update(coarse_resolution=2, short_history=4)


def classify_reasons(reasons):
    mask = 0
    for reason in reasons:
        mask |= REASON_BITS.get(reason, 8)
    return mask


def reassess(original):
    """Use already measured audit metrics; never fill absent data or infer proof."""
    row = dict(original)
    original_checks = [dict(check) for check in original['checks']]
    financial = row.get('price') is True or any(check['id'] in ('native_cadence', 'price_definition') for check in original_checks)
    classification = next((check for check in original_checks if check['id'] == 'series_type'), None)
    row['price'] = financial if classification is None or classification['status'] == 'PASS' else None
    seconds = row.get('native_seconds')
    known = type(seconds) in (int, float) and seconds > 0
    checks = [check for check in original_checks if check['id'] not in ('native_cadence', 'required_cadence')]
    passed = known and seconds <= 900
    checks.append(dict(id='required_cadence', status='PASS' if passed else 'FAIL',
                       reason=None if passed else ('coarse_resolution' if known else 'cadence_unknown'),
                       kind=None if passed else ('measured_failure' if known else 'missing_evidence'),
                       evidence=seconds, limit_seconds=900))
    # The audit measured the longest run of missing native observations inside
    # the verified calendar. With a one-minute grid, 14 missing minutes is the
    # largest run compatible with observations no more than 15 minutes apart.
    for check in checks:
        if check['id'] == 'longest_gap' and financial and known:
            longest = (row.get('coverage') or {}).get('longest_missing_seconds')
            if type(longest) in (int, float) and longest >= 0:
                passed = longest <= max(0, 900 - seconds)
                check.update(status='PASS' if passed else 'FAIL', reason=None if passed else 'long_gaps',
                             kind=None if passed else 'measured_failure', evidence=longest,
                             limit_seconds=max(0, 900 - seconds))
    failures = [check for check in checks if check['status'] == 'FAIL']
    row.update(checks=checks, decision='INELIGIBLE' if failures else 'ELIGIBLE',
               reasons=list(dict.fromkeys(check['reason'] for check in failures)))
    row['failure_mask'] = classify_reasons(row['reasons'])
    return row


def visible_counts(buckets, cap=4000):
    """Keep every nonempty combination visible; each square is still one series."""
    counts = {item['mask']: item['count'] for item in buckets}
    total = sum(counts.values())
    if total <= cap:
        return counts
    result = {mask: 1 for mask in counts}
    remaining = cap - len(result)
    weight = total - len(result)
    remainders = []
    for mask, count in counts.items():
        extra, remainder = divmod(remaining * (count - 1), weight)
        result[mask] += extra
        remainders.append((remainder, mask))
    for _, mask in sorted(remainders, key=lambda item: (-item[0], item[1]))[:cap - sum(result.values())]:
        result[mask] += 1
    return result

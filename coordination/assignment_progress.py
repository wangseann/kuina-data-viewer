"""Advisory worker status, bound to permanent GitHub starts; never availability."""
import json

from coordination.github_assignments import batch, digest, integer, stamp
from coordination.task_manager import PEOPLE, now, require

SCHEMA = 'kuina-assignment-progress-v1'
MAX_RECORDS = 16
MAX_JSON_BYTES = 16384
BINDING = ('batch_id', 'catalogue_generation', 'definition_sha256', 'person',
           'assignment_issue', 'preparation_sha256', 'working_request_issue')
FIELDS = BINDING + ('status', 'report_at', 'report_sha256')
STATUSES = ('active', 'blocked', 'awaiting_verification')


def binding(item):
    return {key: item['work_proof_sha256'] if key == 'preparation_sha256' else item[key]
            for key in BINDING}


def validate_request(value):
    require(type(value) is dict and set(value) == set(BINDING), 'Closed progress binding required')
    batch(value['batch_id'])
    require(value['batch_id'].startswith('unique-') and value['person'] in PEOPLE and
            all(digest(value[key]) for key in ('catalogue_generation', 'definition_sha256', 'preparation_sha256')) and
            integer(value['assignment_issue']) and integer(value['working_request_issue']), 'Invalid progress binding')
    return value


def requests(ledger):
    result = [binding(item) for item in ledger['assignments'].values()
              if item['batch_id'].startswith('unique-') and item['status'] == 'active'
              and item['working_request_issue'] is not None]
    return [validate_request(item) for item in result]


def pages(ledger):
    """Chunk by both encoded bytes and count for the existing bounded CLI."""
    page = []
    for item in requests(ledger):
        candidate = page + [item]
        if page and (len(candidate) > MAX_RECORDS or len(json.dumps(candidate).encode()) > MAX_JSON_BYTES):
            yield page
            page = []
        require(len(json.dumps([item]).encode()) <= MAX_JSON_BYTES, 'Single progress request too large')
        page.append(item)
    if page:
        yield page


def validated(ledger, envelope):
    """Ignore unavailable/mismatched evidence; permanent active status survives."""
    if type(envelope) is not dict or set(envelope) != {'schema', 'records'} or envelope['schema'] != SCHEMA:
        return {}
    values = envelope['records']
    if type(values) is not list or len(values) > 20000:
        return {}
    result = {}
    seen = set()
    try:
        for value in values:
            require(type(value) is dict and set(value) == set(FIELDS), 'Closed progress record required')
            validate_request({key: value[key] for key in BINDING})
            require(value['batch_id'] not in seen and value['status'] in STATUSES and
                    digest(value['report_sha256']), 'Invalid advisory progress')
            seen.add(value['batch_id'])
            require(stamp(value['report_at']) <= stamp(now()), 'Future progress report')
            current = ledger['assignments'].get(value['batch_id'])
            if current is not None and current['status'] == 'active' and binding(current) == {key: value[key] for key in BINDING}:
                require(stamp(value['report_at']) >= stamp(current['created_at']), 'Report predates assignment')
                result[value['batch_id']] = value
    except (ValueError, TypeError, KeyError):
        return {}
    return result

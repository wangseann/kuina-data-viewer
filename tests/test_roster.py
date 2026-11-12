"""Roster rollout preserves old snapshots and real assignment/claim boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coordination.github_claims import Native, parse_request
from coordination.task_manager import Hub, digest, read, validate_public_snapshot

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ('juan', 'emily', 'brian', 'amir', 'seann', 'taha', 'saswato', 'th', 'jion')


class RosterTests(unittest.TestCase):
    def test_new_participants_reserve_claim_report_without_rewriting_tasks(self):
        with tempfile.TemporaryDirectory() as temporary:
            hub = Hub(Path(temporary) / 'hub')
            hub.init()
            hub.seed(read(ROOT / 'docs/summary.json'))
            hub.enable_self_service()
            originals = hub.tasks()
            existing = originals[2]
            hub.claim(existing['id'], 'juan')
            owner_path = hub.root / 'work-claims' / existing['id'] / 'owner.json'
            existing_owner = owner_path.read_bytes()
            for number, (person, name) in enumerate((('vitoria', 'Vitoria'), ('olga', 'Olga')), 51):
                with self.subTest(person=person):
                    task = originals[number - 51]
                    payload = dict(version=1, action='assign', task_id=task['id'], person=person)
                    issue = dict(number=number, title='[Kuina claim] ' + task['id'],
                                 body='<!-- kuina-request-v1\n' + json.dumps(payload) + '\n-->',
                                 user={'login': 'volunteer'})
                    self.assertEqual(parse_request(issue), payload)
                    hub.assign(task['id'], person, number, 'volunteer')
                    self.assertEqual(hub.assignment_status(task['id'])['assignee'], person)
                    owner = hub.claim(task['id'], person)
                    self.assertEqual(owner['task_sha256'], digest(task))
                    hub.report(task['id'], person, 'completed', 'Private evidence')
                    snapshot = hub.snapshot()
                    self.assertEqual(len(snapshot['people']), 11)
                    row = next(p for p in snapshot['people'] if p['id'] == person)
                    self.assertEqual((row['name'], row['awaiting_verification']), (name, 1))
                    self.assertEqual(hub.request_status(task['id'], number)['person'], person)
                    native = Native('host', '/cli', '/hub')
                    with patch.object(native, 'command', return_value=hub.assignment_status(task['id'])):
                        self.assertEqual(native.status(task['id'])['assignee'], person)
                    with patch.object(native, 'command', return_value=hub.request_status(task['id'], number)):
                        self.assertEqual(native.request_status(task['id'], number)['person'], person)
            self.assertEqual(hub.tasks(), originals)
            self.assertEqual(owner_path.read_bytes(), existing_owner)
            self.assertTrue(all('effort' not in t and 'lead' not in t for t in hub.snapshot()['tasks']))

    def test_rollout_accepts_only_complete_old_or_new_roster(self):
        with tempfile.TemporaryDirectory() as temporary:
            hub = Hub(Path(temporary) / 'hub')
            hub.init()
            hub.seed(read(ROOT / 'docs/summary.json'))
            hub.enable_self_service()
            new = hub.snapshot()
        self.assertEqual(len(new['people']), 11)
        self.assertTrue(all(t['status'] == 'available' for t in new['tasks']))
        self.assertIs(validate_public_snapshot(new), new)
        old = copy.deepcopy(new)
        old['people'] = [p for p in old['people'] if p['id'] in LEGACY]
        self.assertEqual({p['id'] for p in old['people']}, set(LEGACY))
        self.assertIs(validate_public_snapshot(old), old)
        for missing in (('olga',), ('jion', 'olga'), ('jion',)):
            invalid = copy.deepcopy(new)
            invalid['people'] = [p for p in invalid['people'] if p['id'] not in missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_public_snapshot(invalid)
        invalid = copy.deepcopy(old)
        task = next(t for t in invalid['tasks'] if t['status'] == 'available')
        task.update(status='active', assignee='vitoria')
        with self.assertRaises(ValueError):
            validate_public_snapshot(invalid)

    def test_legacy_schema_roster_rollout_keeps_assignment_and_lead_membership(self):
        for version in (1, 2):
            with tempfile.TemporaryDirectory() as temporary, self.subTest(version=version):
                hub = Hub(Path(temporary) / 'hub')
                hub.init()
                hub.seed(read(ROOT / 'docs/summary.json'))
                snapshot = hub.snapshot()
                snapshot['schema_version'] = version
                snapshot['tasks'] = [t for t in snapshot['tasks'] if t['assignee'] in LEGACY]
                if version == 2:
                    snapshot['batch_limit'] = 500
                    for task in snapshot['tasks']:
                        task.update(lead=task['assignee'], parent_id=None, batch_number=0, batch_total=0)
                    for person in snapshot['people']:
                        person.update(batched=0, remaining_series=sum(t['affected_series'] for t in snapshot['tasks']
                                      if t['assignee'] == person['id']))
                for person in snapshot['people']:
                    if person['id'] not in LEGACY:
                        person.update(queued=0, load=0)
                        if version == 2:
                            person['remaining_series'] = 0
                self.assertIs(validate_public_snapshot(snapshot), snapshot)
                snapshot['people'] = [p for p in snapshot['people'] if p['id'] in LEGACY]
                self.assertIs(validate_public_snapshot(snapshot), snapshot)
                invalid = copy.deepcopy(snapshot)
                invalid['tasks'][0]['assignee'] = 'olga'
                with self.assertRaises(ValueError):
                    validate_public_snapshot(invalid)
                if version == 2:
                    invalid = copy.deepcopy(snapshot)
                    invalid['tasks'][0]['lead'] = 'vitoria'
                    with self.assertRaises(ValueError):
                        validate_public_snapshot(invalid)

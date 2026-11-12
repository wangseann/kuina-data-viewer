import copy
import unittest
from unittest.mock import patch

from coordination.github_claims import InvalidRequest, NativeFailure, parse_request, process_issue


def issue(action='assign', person='seann', task='batch-synthetic-000001'):
    import json
    label = 'claim' if action == 'assign' else 'release'
    payload = dict(version=1, action=action, task_id=task, person=person)
    if action == 'release': payload['assignment_issue'] = 7
    return dict(number=7, title='[Kuina '+label+'] '+task,
                body='<!-- kuina-request-v1\n'+json.dumps(payload)+'\n-->',
                user=dict(login='wangseann'), labels=[])


class Native:
    def __init__(self):
        self.current = dict(task_id='batch-synthetic-000001', status='available', assignee=None, assignment_issue=None)
        self.calls = 0
        self.race = False
        self.lost_ack = False

    def request_status(self, task_id, number):
        return getattr(self, 'receipt', None)

    def status(self, task_id):
        return dict(self.current)

    def assign(self, task_id, person, number, author):
        self.calls += 1
        if self.race:
            self.current.update(status='assigned', assignee='emily', assignment_issue=6)
            raise NativeFailure('private /secret/path error')
        self.current.update(status='assigned', assignee=person, assignment_issue=number)
        if self.lost_ack:
            raise NativeFailure('lost acknowledgement /private/path')

    def release(self, task_id, person, author, number, assignment_issue, coordinator=False):
        self.calls += 1
        if self.current['status'] == 'active':
            raise NativeFailure('worker already running')
        self.current.update(status='available', assignee=None, assignment_issue=None)


class Github:
    def __init__(self):
        self.results = []

    def finish(self, source, result):
        self.results.append(result)


class GithubClaimTests(unittest.TestCase):
    def test_request_contract_rejects_commands_extra_fields_and_spoofed_actor(self):
        self.assertEqual(parse_request(issue())['person'], 'seann')
        for mutation in ('extra', 'actor', 'duplicate', 'person', 'title', 'pull'):
            data = copy.deepcopy(issue())
            if mutation == 'extra': data['body'] = data['body'].replace('"version": 1', '"version": 1, "command":"anything"')
            if mutation == 'actor': data['user']['login'] = 'x;danger'
            if mutation == 'duplicate': data['body'] += data['body']
            if mutation == 'person': data['body'] = data['body'].replace('seann', 'stranger')
            if mutation == 'title': data['title'] = '[Kuina release] batch-synthetic-000001'
            if mutation == 'pull': data['pull_request'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(InvalidRequest):
                parse_request(data)

    def test_claim_is_confirmed_only_after_native_state_matches(self):
        native, github = Native(), Github()
        result = process_issue(issue(), github, native, 'wangseann')
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(native.current['assignee'], 'seann')
        self.assertEqual(native.calls, 1)
        self.assertEqual(github.results[0]['person'], 'seann')
        process_issue(issue(), github, native, 'wangseann')
        self.assertEqual(native.calls, 1)

    def test_conflicting_claim_and_race_never_reassign(self):
        for racing in (False, True):
            native, github = Native(), Github()
            if racing: native.race = True
            else: native.current.update(status='assigned', assignee='emily', assignment_issue=6)
            result = process_issue(issue(), github, native, 'wangseann')
            self.assertEqual(result['status'], 'rejected')
            self.assertEqual(native.current['assignee'], 'emily')
            self.assertNotIn('/secret/', str(github.results))

    def test_uncertain_ack_is_reconciled_without_repeating_mutation(self):
        native, github = Native(), Github()
        native.lost_ack = True
        result = process_issue(issue(), github, native, 'wangseann')
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(native.calls, 1)

    def test_active_work_cannot_be_released_from_web(self):
        native, github = Native(), Github()
        native.current.update(status='active', assignee='seann', assignment_issue=7)
        result = process_issue(issue('release'), github, native, 'wangseann')
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(native.current['status'], 'active')
        self.assertEqual(native.calls, 0)

    def test_synthetic_test_issues_are_ignored_by_production_poll(self):
        from coordination.github_claims import is_request_issue
        data = issue();data['labels'] = [dict(name='kuina-integration-test')]
        self.assertFalse(is_request_issue(data))
        self.assertTrue(is_request_issue(issue()))

    def test_poll_handles_success_and_keeps_private_errors_pending(self):
        from coordination.github_claims import poll
        github,native=Github(),Native()
        github.owner='wangseann';github.requests=lambda:[issue()]
        config=dict(repo='wangseann/kuina-data-viewer',host='example',cli='example',hub='example')
        with patch('coordination.github_claims.GitHub',return_value=github),patch('coordination.github_claims.Native',return_value=native):
            result=poll(config)
        self.assertEqual(result[0]['issue'],7)
        self.assertEqual(result[0]['status'],'confirmed')
        native.status=lambda unused:(_ for _ in ()).throw(NativeFailure('/private/error'))
        with patch('coordination.github_claims.GitHub',return_value=github),patch('coordination.github_claims.Native',return_value=native):
            pending=poll(config)
        self.assertEqual(pending[0]['status'],'pending')
        self.assertNotIn('/private/',str(pending))

    def test_paginated_discovery_does_not_hide_claims_behind_ordinary_issues(self):
        from coordination.github_claims import GitHub
        client=GitHub('wangseann/kuina-data-viewer')
        calls=[]
        def api(path,fields):
            calls.append(fields['page'])
            return [dict(number=i,title='Ordinary issue')for i in range(100)] if fields['page']==1 else [issue()]
        client.api=api
        self.assertEqual(client.requests(),[issue()])
        self.assertEqual(calls,[1,2])

    def test_stale_release_cannot_cancel_a_newer_reservation(self):
        native, github = Native(), Github()
        native.current.update(status='assigned', assignee='seann', assignment_issue=99)
        result = process_issue(issue('release'), github, native, 'wangseann')
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(native.calls, 0)

    def test_committed_receipt_wins_over_a_later_assignment_change(self):
        for action in ('assign','release'):
            native, github = Native(), Github()
            if action == 'release':
                native.current.update(status='assigned', assignee='seann', assignment_issue=7)
            def mutation(*unused, **options):
                native.receipt = dict(task_id=native.current['task_id'],request_issue=7,
                                      action=action,person='seann',status='confirmed' if action=='assign' else 'released')
                native.current.update(status='assigned',assignee='emily',assignment_issue=99)
            if action == 'assign': native.assign = mutation
            else: native.release = mutation
            result = process_issue(issue(action),github,native,'wangseann')
            self.assertEqual(result['status'],'confirmed' if action=='assign' else 'released')
            self.assertEqual(native.current['assignee'],'emily')

    def test_terminal_notification_retry_does_not_repeat_queue_action(self):
        from coordination.github_claims import poll
        github, native = Github(), Native()
        github.owner = 'wangseann'
        github.requests = lambda:[issue()]
        notifications = []
        def finish(source, result):
            notifications.append(result)
            if len(notifications) == 1:
                import subprocess
                raise subprocess.CalledProcessError(1, 'notification')
        github.finish = finish
        config = dict(repo='wangseann/kuina-data-viewer',host='example',cli='example',hub='example')
        state, saved = {}, []
        with patch('coordination.github_claims.GitHub',return_value=github), patch('coordination.github_claims.Native',return_value=native):
            poll(config,state,lambda:saved.append(copy.deepcopy(state)))
            self.assertEqual(saved[0]['completed']['7']['status'], 'confirmed')
            native.current.update(status='available', assignee=None, assignment_issue=None)
            poll(config,state)
        self.assertEqual(native.calls, 1)
        self.assertEqual(native.current['status'], 'available')

    def test_pending_requests_do_not_starve_newer_claims(self):
        from coordination.github_claims import poll
        github,native=Github(),Native()
        github.owner='wangseann'
        requests=[dict(issue(),number=n)for n in range(1,22)]
        github.requests=lambda:requests
        config=dict(repo='wangseann/kuina-data-viewer',host='example',cli='example',hub='example')
        attempts=[]
        def process(source,*unused):
            attempts.append(source['number'])
            if source['number']<21:raise NativeFailure('still pending')
            return dict(status='confirmed')
        state={}
        with patch('coordination.github_claims.GitHub',return_value=github),patch('coordination.github_claims.Native',return_value=native),patch('coordination.github_claims.process_issue',side_effect=process):
            poll(config,state);poll(config,state)
        self.assertEqual(attempts[:20],list(range(1,21)))
        self.assertEqual(attempts[20],21)


if __name__ == '__main__':
    unittest.main()

"""GitHub request broker. It assigns queue records, never executes dataset work."""
import json
import re
import shlex
import subprocess

PEOPLE = ('juan', 'emily', 'brian', 'amir', 'seann', 'taha', 'saswato', 'th', 'jion')
MARKER = '<!-- kuina-request-v1'
TASK_ID = re.compile(r'[A-Za-z0-9_-]{1,96}')
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})')


class InvalidRequest(ValueError):
    pass


class NativeFailure(RuntimeError):
    """Private diagnostics stay in local logs, never GitHub comments."""


def is_request_issue(issue):
    labels = [label.get('name') for label in issue.get('labels', []) if isinstance(label, dict)]
    return ('pull_request' not in issue and 'kuina-integration-test' not in labels and
            isinstance(issue.get('title'), str) and
            issue['title'].startswith(('[Kuina claim] ', '[Kuina release] ')))


def parse_request(issue):
    if 'pull_request' in issue:
        raise InvalidRequest('A pull request is not a batch request.')
    body = issue.get('body')
    if not isinstance(body, str) or len(body.encode()) > 16384 or body.count(MARKER) != 1:
        raise InvalidRequest('Use the claim form from the task tracker.')
    match = re.search(re.escape(MARKER) + r'\s*\n(.*?)\n-->', body, re.S)
    try:
        request = json.loads(match.group(1)) if match else None
    except (ValueError, TypeError):
        raise InvalidRequest('The request payload could not be read.')
    fields = {'version', 'action', 'task_id', 'person'}
    if isinstance(request, dict) and request.get('action') == 'release':
        fields.add('assignment_issue')
    if not isinstance(request, dict) or set(request) != fields:
        raise InvalidRequest('The request fields do not match the tracker form.')
    if type(request['version']) is not int or request['version'] != 1:
        raise InvalidRequest('Unsupported request version.')
    if request['action'] == 'release' and (type(request['assignment_issue']) is not int or request['assignment_issue'] <= 0):
        raise InvalidRequest('Release requests must identify the displayed reservation.')
    if request['action'] not in ('assign', 'release') or request['person'] not in PEOPLE:
        raise InvalidRequest('Choose a registered participant and action.')
    if not isinstance(request['task_id'], str) or not TASK_ID.fullmatch(request['task_id']):
        raise InvalidRequest('Invalid batch identifier.')
    title = '[Kuina '+('claim' if request['action'] == 'assign' else 'release')+'] '+request['task_id']
    author = issue.get('user', {}).get('login')
    if issue.get('title') != title or not isinstance(author, str) or not LOGIN.fullmatch(author):
        raise InvalidRequest('Request title or GitHub author is invalid.')
    if type(issue.get('number')) is not int or issue['number'] <= 0:
        raise InvalidRequest('Invalid issue number.')
    return request


def process_issue(issue, github, native, owner, remember=None):
    """Confirm only observed Native state; reconcile a lost write acknowledgement."""
    def finish(result):
        if remember is not None:
            remember(result)
        github.finish(issue, result)
        return result

    try:
        request = parse_request(issue)
    except InvalidRequest as error:
        result = dict(status='rejected', message=str(error))
        return finish(result)
    task_id, person = request['task_id'], request['person']
    author = issue['user']['login']
    result = dict(task_id=task_id, person=person, issue=issue['number'])
    previous = native.request_status(task_id, issue['number'])
    if previous is not None:
        if previous['action'] != request['action'] or previous['person'] != person:
            result.update(status='rejected', message='This request number was already used for another action.')
        else:
            result.update(status=previous['status'], message='This request was already processed. Check the current private assignment before working.')
        return finish(result)
    before = native.status(task_id)
    if request['action'] == 'assign':
        if before['assignee'] == person and before['status'] in ('assigned', 'active', 'blocked', 'awaiting_verification'):
            result.update(status='confirmed', message='This batch is already assigned to you.')
        elif before['status'] != 'available' or before['assignee'] is not None:
            result.update(status='rejected', message='This batch is no longer available. Choose another available batch.')
        else:
            try:
                native.assign(task_id, person, issue['number'], author)
            except NativeFailure:
                pass  # Query the authoritative record instead of repeating the write.
            recorded = native.request_status(task_id, issue['number'])
            if recorded is not None and recorded['action'] == 'assign' and recorded['person'] == person:
                result.update(status='confirmed', message='Reservation request confirmed. Check the current private assignment before working.')
                return finish(result)
            after = native.status(task_id)
            if after['assignee'] == person and after['status'] in ('assigned', 'active', 'blocked', 'awaiting_verification'):
                result.update(status='confirmed', message='Reservation confirmed in the shared queue.')
            elif after['assignee'] is not None or after['status'] != 'available':
                result.update(status='rejected', message='Another claim won the reservation. Choose another available batch.')
            else:
                raise NativeFailure('Reservation not confirmed; keep request open for a later check.')
    else:
        if before['status'] == 'available' and before['assignee'] is None:
            result.update(status='released', message='The batch is already available.')
        elif before['status'] != 'assigned' or before['assignee'] != person or before['assignment_issue'] != request['assignment_issue']:
            result.update(status='rejected', message='Started work cannot be released here. Reconcile it through the private hub.')
        else:
            try:
                native.release(task_id, person, author, issue['number'], request['assignment_issue'], coordinator=author.casefold() == owner.casefold())
            except NativeFailure:
                pass
            recorded = native.request_status(task_id, issue['number'])
            if recorded is not None and recorded['action'] == 'release' and recorded['person'] == person:
                result.update(status='released', message='Reservation release confirmed. Later assignments are separate.')
                return finish(result)
            after = native.status(task_id)
            if after['status'] == 'available' and after['assignee'] is None:
                result.update(status='released', message='Reservation released; the batch is available.')
            elif after['status'] == 'assigned' and after['assignee'] == person:
                result.update(status='rejected', message='Only the reservation requester or coordinator can release it.')
            else:
                result.update(status='rejected', message='The batch has started or changed. No running work was released.')
    return finish(result)


class GitHub:
    def __init__(self, repo, executable='/opt/homebrew/bin/gh'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid repository')
        self.repo, self.executable = repo, executable
        self.owner = repo.split('/')[0]

    def api(self, path, method='GET', fields=None):
        args = [self.executable, 'api', '--method', method, path]
        payload = None
        if method == 'GET':
            for key, value in (fields or {}).items():
                args.extend(['-f', key+'='+str(value)])
        elif fields is not None:
            args.extend(['--input', '-'])
            payload = json.dumps(fields).encode()
        raw = subprocess.check_output(args, input=payload, stderr=subprocess.PIPE, timeout=45)
        if len(raw) > 2*1024*1024:
            raise ValueError('GitHub response exceeds the request bound')
        return json.loads(raw) if raw.strip() else None

    def requests(self):
        requests = []
        for page in range(1, 201):
            issues = self.api('repos/'+self.repo+'/issues', fields=dict(state='open', per_page=100, page=page, sort='created', direction='asc'))
            requests.extend(issue for issue in issues if is_request_issue(issue))
            if len(issues) < 100:
                return requests
        raise ValueError('Open issue discovery exceeds the 20,000-issue safety bound')

    def finish(self, issue, result):
        marker = '<!-- kuina-request-result-v1:'+str(issue['number'])+' -->'
        comments = self.api('repos/'+self.repo+'/issues/'+str(issue['number'])+'/comments', fields=dict(per_page=100))
        exists = any(comment.get('user', {}).get('login', '').casefold() == self.owner.casefold() and
                     marker in (comment.get('body') or '') for comment in comments)
        if not exists:
            lines = [marker, '**'+result['status'].capitalize()+'**: '+result['message']]
            if 'task_id' in result:
                lines.append('Batch: `'+result['task_id']+'` · Participant: '+result['person'])
            lines.append('This closes the request, not the dataset repair. Verify your private queue assignment before starting work.')
            self.api('repos/'+self.repo+'/issues/'+str(issue['number'])+'/comments', 'POST', dict(body='\n\n'.join(lines)))
        self.api('repos/'+self.repo+'/issues/'+str(issue['number']), 'PATCH',
                 dict(state='closed', state_reason='completed' if result['status'] != 'rejected' else 'not_planned'))


class Native:
    def __init__(self, host, cli, hub):
        self.host, self.cli, self.hub = host, cli, hub

    def command(self, *arguments):
        args = ['python3', '-B', self.cli, '--hub', self.hub, *arguments]
        command = ' '.join(shlex.quote(str(part)) for part in args)
        result = subprocess.run(['/usr/bin/ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', self.host, command],
                                capture_output=True, timeout=60)
        if result.returncode:
            raise NativeFailure('Native queue command failed; inspect private diagnostics.')
        if len(result.stdout) > 32768:
            raise NativeFailure('Native queue response exceeds the status bound.')
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise NativeFailure('Native queue did not return a valid status.')

    def status(self, task_id):
        data = self.command('assignment-status', task_id)
        if set(data) != {'task_id', 'status', 'assignee', 'assignment_issue'} or data['task_id'] != task_id:
            raise NativeFailure('Unexpected assignment status contract.')
        if data['status'] not in ('available', 'assigned', 'active', 'blocked', 'awaiting_verification', 'verified', 'batched'):
            raise NativeFailure('Unknown assignment state.')
        if data['assignee'] is not None and data['assignee'] not in PEOPLE:
            raise NativeFailure('Unknown assignee.')
        if data['assignment_issue'] is not None and (type(data['assignment_issue']) is not int or data['assignment_issue'] <= 0):
            raise NativeFailure('Invalid assignment request reference.')
        return data

    def request_status(self, task_id, number):
        data = self.command('request-status', task_id, '--issue', str(number))
        if data is None:
            return None
        fields = {'task_id', 'request_issue', 'action', 'person', 'status'}
        if (not isinstance(data, dict) or set(data) != fields or data['task_id'] != task_id or
                data['request_issue'] != number or data['action'] not in ('assign', 'release') or
                data['person'] not in PEOPLE or data['status'] != {'assign':'confirmed', 'release':'released'}[data['action']]):
            raise NativeFailure('Unexpected request receipt.')
        return data

    def assign(self, task_id, person, number, author):
        return self.command('assign', task_id, '--person', person, '--issue', str(number), '--github-author', author)

    def release(self, task_id, person, author, number, assignment_issue, coordinator=False):
        args = ['release-assignment', task_id, '--person', person, '--github-author', author,
                '--request-issue', str(number), '--assignment-issue', str(assignment_issue)]
        if coordinator:
            args.append('--coordinator')
        return self.command(*args)


def poll(config, state=None, save_state=None):
    github = GitHub(config['repo'], config.get('gh', '/opt/homebrew/bin/gh'))
    native = Native(config['host'], config['cli'], config['hub'])
    if state is None:
        state = {}
    cursor = state.get('last_issue', 0)
    if type(cursor) is not int or cursor < 0:
        raise ValueError('Invalid broker continuation cursor')
    completed = state.setdefault('completed', {})
    requests = sorted(github.requests(), key=lambda issue:issue['number'])
    ordered = [issue for issue in requests if issue['number'] > cursor]+[issue for issue in requests if issue['number'] <= cursor]
    results = []
    for issue in ordered[:20]:
        try:
            key = str(issue['number'])
            def remember(value):
                completed[key] = value
                if save_state is not None:
                    save_state()
            if key in completed:
                result = completed[key]
                github.finish(issue, result)
            else:
                result = process_issue(issue, github, native, github.owner, remember)
            result.setdefault('issue', issue['number'])
            results.append(result)
        except (NativeFailure, subprocess.SubprocessError, OSError) as error:
            results.append(dict(issue=issue['number'], status='pending', message=type(error).__name__))
        state['last_issue'] = issue['number']
    return results


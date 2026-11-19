"""Publish three strict assignment assets, reconciling only ledger CAS commits.

Call under the existing counts publisher lock. No Native reads, ledger writes or
private report text belongs here. Git mutations are limited to reviewed metadata.
"""
from copy import deepcopy
from datetime import timezone
import os
from pathlib import Path
import re
import subprocess
import tempfile

from coordination.assignment_publication import render_assets
from coordination.github_assignments import stamp
from coordination.github_assignments_v2 import Assignments
from coordination.task_manager import require, validate_public_snapshot
from coordination.unique_queue import file_bytes, parse
import counts
import unique_dashboard

UNIQUE_ASSETS = frozenset(('docs/unique.html', 'docs/unique-summary.json', 'docs/unique-tasks.json'))
COUNTS_ASSETS = frozenset(('docs/index.html', 'docs/summary.json', 'docs/tasks-summary.json'))
GENERATED = UNIQUE_ASSETS | COUNTS_ASSETS
ORIGINS = ('https://github.com/wangseann/kuina-data-viewer.git',
           'git@github.com:wangseann/kuina-data-viewer.git')
LEDGER = 'coordination/assignments.json'


def stable_generated_at(ledger, initialized_at):
    times = [stamp(initialized_at)]
    times.extend(stamp(item['updated_at']) for item in ledger['assignments'].values())
    times.extend(stamp(item['recorded_at']) for item in ledger['receipts'].values())
    return max(times).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


class Synchronizer:
    def __init__(self, project, github, ledger_path=LEDGER, branch='main', expected_origins=ORIGINS, progress_provider=None):
        self.project = Path(project).absolute()
        require(not self.project.is_symlink() and self.project.is_dir(), 'Invalid publication checkout')
        require(ledger_path == LEDGER and branch == 'main', 'Only the reviewed assignment ledger/main route is supported')
        self.github = github
        self.ledger_path = ledger_path
        self.branch = branch
        self.expected_origins = tuple(expected_origins)
        self.progress_provider = progress_provider

    def git(self, *args):
        command = ['/usr/bin/git', '-c', 'credential.helper=', '-c',
                   'credential.helper=!/opt/homebrew/bin/gh auth git-credential', *args]
        return subprocess.check_output(command, cwd=self.project, text=True, stderr=subprocess.PIPE,
                                       timeout=60, env=dict(os.environ, GIT_TERMINAL_PROMPT='0',
                                                            GIT_EDITOR='true')).strip()

    def require_clean(self):
        require(not self.git('status', '--porcelain', '--untracked-files=all'),
                'Checkout has edits; preserve them before publication')
        # rev-parse may return paths relative to the checkout.
        for operation in ('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD'):
            path = Path(self.git('rev-parse', '--git-path', operation))
            require(not (path if path.is_absolute() else self.project / path).exists(),
                    'Git operation already pending')

    def read_asset(self, name, maximum):
        require(name in GENERATED, 'Unapproved metadata asset')
        path = self.project / name
        require(not (self.project / 'docs').is_symlink(), 'Symlink publication directory')
        return file_bytes(path, maximum)

    def validate_pending(self, paths):
        require(bool(paths) and set(paths) <= GENERATED, 'Pending commit includes unreviewed files')
        if set(paths) & {'docs/index.html', 'docs/summary.json'}:
            summary = counts.validate(parse(self.read_asset('docs/summary.json', 128 * 1024)))
            require(self.read_asset('docs/index.html', 32 * 1024 * 1024).decode() == counts.render(summary),
                    'Pending counts HTML differs from the approved renderer')
            previous_raw = self.git('show', 'origin/main:docs/summary.json')
            require(len(previous_raw.encode()) <= 128 * 1024, 'Published counts exceed bound')
            previous = counts.validate(parse(previous_raw))
            require(stamp(summary['audit_utc']) >= stamp(previous['audit_utc']), 'Older pending audit cannot publish')
            require(previous['schema'] != 4 or summary['schema'] == 4, 'Required counts profile cannot regress')
            if previous['schema'] == summary['schema'] == 4:
                require(stamp(summary['assessment_utc']) >= stamp(previous['assessment_utc']),
                        'Older pending metadata assessment cannot publish')
        if 'docs/tasks-summary.json' in paths:
            validate_public_snapshot(parse(self.read_asset('docs/tasks-summary.json', 16 * 1024 * 1024)))
        if set(paths) & UNIQUE_ASSETS:
            summary = parse(self.read_asset('docs/unique-summary.json', 64 * 1024))
            tasks = parse(self.read_asset('docs/unique-tasks.json', 8 * 1024 * 1024))
            unique_dashboard.validate(summary, tasks)
            html = self.read_asset('docs/unique.html', 16 * 1024 * 1024)
            payloads = re.findall(r'<script id="unique-data" type="application/json">(.*?)</script>',
                                  html.decode(), flags=re.DOTALL)
            require(len(payloads) == 1, 'Pending assignment HTML payload missing or repeated')
            embedded = parse(payloads[0])
            require(type(embedded) is dict and set(embedded) ==
                    {'summary', 'tasks', 'category_labels', 'status_labels'} and
                    embedded['summary'] == summary and embedded['tasks'] == tasks,
                    'Pending HTML and JSON metadata differ')
            with tempfile.TemporaryDirectory(prefix='kuina-pending-assignment-') as folder:
                # Preserve the embedded key order: sidecars intentionally use
                # sorted JSON, while the HTML builder preserves input order.
                unique_dashboard.build(embedded['summary'], embedded['tasks'], Path(folder))
                require(html == (Path(folder) / 'unique.html').read_bytes(), 'Pending assignment HTML differs')

    def commit_paths(self, commit):
        return self.git('diff-tree', '--root', '--no-commit-id', '--name-only', '-r', commit).splitlines()

    def check_remote_range(self):
        for commit in self.git('rev-list', 'HEAD..origin/main').splitlines():
            parents = self.git('rev-list', '--parents', '-n', '1', commit).split()
            require(len(parents) == 2 and self.commit_paths(commit) == [self.ledger_path],
                    'Remote history includes unreviewed source or non-ledger changes')

    def prepare_branch(self):
        self.require_clean()
        require(self.git('remote', 'get-url', 'origin') in self.expected_origins,
                'Unexpected publication repository')
        require(self.git('symbolic-ref', '--short', 'HEAD') == self.branch, 'Publication must use main')
        self.git('fetch', '--no-tags', 'origin', self.branch)
        ahead, behind = map(int, self.git('rev-list', '--left-right', '--count', 'HEAD...origin/main').split())
        if ahead:
            require(ahead == 1, 'Only one pending metadata commit can reconcile automatically')
            pending = self.git('rev-parse', 'HEAD')
            require(len(self.git('rev-list', '--parents', '-n', '1', pending).split()) == 2,
                    'Pending merge commit requires review')
            self.validate_pending(self.commit_paths(pending))
        if behind:
            self.check_remote_range()
            if ahead:
                base = self.git('merge-base', 'HEAD', 'origin/main')
                try:
                    self.git('rebase', '--onto', 'origin/main', base)
                except (subprocess.SubprocessError, OSError):
                    self.git('rebase', '--abort')
                    raise ValueError('Metadata rebase conflicted; no publication was pushed') from None
            else:
                self.git('merge', '--ff-only', 'origin/main')
        self.require_clean()
        return bool(ahead)

    def write_assets(self, assets):
        require(set(assets) == UNIQUE_ASSETS and all(type(raw) is bytes for raw in assets.values()),
                'Renderer must return exactly the three assignment assets')
        for name, raw in assets.items():
            maximum = 64 * 1024 if name.endswith('summary.json') else 16 * 1024 * 1024
            require(len(raw) <= maximum, 'Assignment asset exceeds bound')
            path = self.project / name
            require(not (self.project / 'docs').is_symlink() and not path.is_symlink(), 'Symlink publication asset')
        for name, raw in assets.items():
            path = self.project / name
            descriptor, temporary = tempfile.mkstemp(prefix='.assignment-', dir=path.parent)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    os.fchmod(stream.fileno(), 0o644)
                    stream.write(raw)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def push(self):
        local = self.git('rev-parse', 'HEAD')
        try:
            self.git('push', 'origin', 'HEAD:main')
        except (subprocess.SubprocessError, OSError):
            remote = self.git('ls-remote', 'origin', 'refs/heads/main').split()
            if remote and remote[0] == local:
                return True  # Observed success after a lost acknowledgement.
            # One bounded reconciliation. Do not push an older ledger snapshot
            # over a newer confirmed reservation; the next poll renders it fresh.
            self.prepare_branch()
            return False
        return True

    def publish(self, summary, catalogue, initialized_at):
        pending = self.prepare_branch()
        observed = Assignments(self.github, None, None, path=self.ledger_path, branch=self.branch).snapshot()
        require(self.git('rev-parse', 'HEAD:' + self.ledger_path) == observed['ledger_sha'],
                'Fetched branch and observed GitHub ledger differ; retry a fresh poll')
        ledger = observed['ledger']
        generated_at = stable_generated_at(ledger, initialized_at)
        progress = None
        if self.progress_provider is not None:
            from coordination.assignment_progress import validated
            try:
                progress = self.progress_provider(deepcopy(observed))
            except Exception:
                # This optional private transport cannot release or block a permanent reservation.
                progress = None
            refreshed = Assignments(self.github, None, None, path=self.ledger_path, branch=self.branch).snapshot()
            require(refreshed['ledger_sha'] == observed['ledger_sha'], 'GitHub authority changed during progress query')
            advisory = validated(ledger, progress)
            if advisory:
                generated_at = max([stamp(generated_at)] + [stamp(value['report_at']) for value in advisory.values()]).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        previous_tasks = self.project / 'docs/unique-tasks.json'
        if self.progress_provider is not None and previous_tasks.exists():
            previous_time = parse(self.read_asset('docs/unique-tasks.json', 8 * 1024 * 1024))['generated_at']
            generated_at = max((generated_at, previous_time), key=stamp)
        assets = render_assets(summary, catalogue, ledger, generated_at, progress=progress)
        previous = self.project / 'docs/unique-tasks.json'
        if previous.exists():
            saved = parse(self.read_asset('docs/unique-tasks.json', 8 * 1024 * 1024))
            previous_summary = parse(self.read_asset('docs/unique-summary.json', 64 * 1024))
            unique_dashboard.validate(previous_summary, saved)
            unique_dashboard.require_current_eligibility(previous_summary, summary)
            require(stamp(summary['generated_at']) >= stamp(previous_summary['generated_at']),
                    'Older grouping summary cannot replace current publication')
            require(stamp(generated_at) >= stamp(saved['generated_at']), 'Older assignment metadata cannot replace current publication')
        self.write_assets(assets)
        changed = self.git('diff', '--name-only').splitlines()
        require(set(changed) <= UNIQUE_ASSETS, 'Unexpected generated changes')
        if changed:
            self.git('add', '--', *sorted(UNIQUE_ASSETS))
            require(set(self.git('diff', '--cached', '--name-only').splitlines()) <= UNIQUE_ASSETS,
                    'Unreviewed staged changes')
            if pending:
                self.git('commit', '--amend', '--no-edit')
            else:
                self.git('commit', '-m', 'Update confirmed GitHub assignment status')
            pending = True
        if not pending:
            return dict(status='UNCHANGED', generated_at=generated_at, ledger_sha=observed['ledger_sha'])
        self.validate_pending(self.commit_paths('HEAD'))
        published = self.push()
        return dict(status='PUBLISHED' if published else 'RETRY_PENDING', generated_at=generated_at,
                    ledger_sha=observed['ledger_sha'], commit=self.git('rev-parse', 'HEAD'))

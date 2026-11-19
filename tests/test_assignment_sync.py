"""Real local bare Git/clone races; no GitHub, credentials or network."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from coordination.assignment_publication import render_assets
from tests.test_unique_dashboard import fixtures
try:
    from coordination.assignment_sync import Synchronizer, stable_generated_at
except ImportError:
    Synchronizer = stable_generated_at = None


class GitSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bare = self.root / 'remote.git'
        self.a, self.b = self.root / 'a', self.root / 'b'
        self.run_git(self.root, 'init', '--bare', str(self.bare))
        self.run_git(self.root, 'clone', str(self.bare), str(self.a))
        self.run_git(self.a, 'checkout', '-b', 'main')
        self.identity(self.a)
        self.summary, tasks = fixtures()
        row = tasks['batches'][0]
        self.batch = row['id']
        self.catalogue = dict(schema='kuina-public-assignment-catalogue-v1', generation='b' * 64,
            batches=[dict({k: row[k] for k in ('id','category','target_count','series_count')},
                          definition_sha256='c'*64, assignment_enabled=True)])
        self.at = '2026-11-19T00:00:00Z'
        self.ledger = dict(schema='kuina-github-assignments-v1', migration=dict(
            complete=True, source_sha256='a'*64, catalogue_generation='b'*64), assignments={}, receipts={})
        (self.a / 'coordination').mkdir()
        (self.a / 'docs').mkdir()
        (self.a / 'README').write_text('source unchanged')
        self.write_ledger(self.a)
        for name, raw in render_assets(self.summary,self.catalogue,self.ledger,self.at).items():
            (self.a / name).write_bytes(raw)
        self.commit(self.a, 'baseline')
        self.run_git(self.a, 'push', '-u', 'origin', 'main')
        self.run_git(self.bare, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        self.run_git(self.root, 'clone', str(self.bare), str(self.b))
        self.identity(self.b)
        fixture = self
        class FakeGitHub:
            repo = 'wangseann/kuina-data-viewer'
            owner = 'wangseann'
            gets = 0
            def api(self, path, method='GET', fields=None):
                fixture.assertEqual(method,'GET')
                self.gets += 1
                raw = subprocess.check_output(['/usr/bin/git','--git-dir',str(fixture.bare),
                    'show','main:coordination/assignments.json'])
                return dict(type='file',encoding='base64',size=len(raw),
                    content=base64.b64encode(raw).decode(),
                    sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
        self.gh = FakeGitHub()

    @staticmethod
    def run_git(path, *args):
        return subprocess.check_output(['/usr/bin/git', *args], cwd=path,
                                       stderr=subprocess.PIPE, text=True).strip()
    def identity(self,path):
        self.run_git(path,'config','user.name','Temporary Fixture')
        self.run_git(path,'config','user.email','fixture@example.invalid')
    def commit(self,path,message):
        self.run_git(path,'add','--all')
        self.run_git(path,'commit','-m',message)
    def write_ledger(self,path):
        (path/'coordination/assignments.json').write_text(json.dumps(self.ledger,sort_keys=True)+'\n')
    def sync(self):
        return Synchronizer(self.a,self.gh,expected_origins=(str(self.bare),))
    def publish(self,sync=None):
        return (sync or self.sync()).publish(self.summary,self.catalogue,self.at)
    def assign_remote(self):
        self.ledger['assignments'][self.batch] = dict(batch_id=self.batch,person='seann',author='alice',
            assignment_issue=4,status='assigned',definition_sha256='c'*64,catalogue_generation='b'*64,
            created_at=self.at,updated_at='2026-11-19T01:00:00Z',origin='github',
            work_proof_sha256=None,working_request_issue=None)
        self.ledger['receipts']['4'] = dict(request_issue=4,batch_id=self.batch,action='assign',person='seann',
            author='alice',assignment_issue=None,proof_sha256=None,status='confirmed',
            recorded_at='2026-11-19T01:00:00Z',definition_sha256='c'*64,catalogue_generation='b'*64,origin='github')
        self.write_ledger(self.b);self.commit(self.b,'GitHub ledger CAS')
        self.run_git(self.b,'push','origin','main')

    def test_ledger_only_fast_forward_and_one_observed_snapshot(self):
        self.assertIsNotNone(Synchronizer)
        self.assign_remote()
        result=self.publish()
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(self.gh.gets,1)
        data=json.loads((self.a/'docs/unique-tasks.json').read_text())
        self.assertEqual(data['batches'][0]['assignee'],'seann')
        self.assertEqual(data['generated_at'],'2026-11-19T01:00:00Z')
        self.assertEqual(self.run_git(self.a,'status','--porcelain'),'')
        self.assertEqual(self.run_git(self.a,'rev-parse','HEAD'),self.run_git(self.bare,'rev-parse','main'))
        self.assertEqual(json.loads(self.run_git(self.bare,'show','main:coordination/assignments.json')),self.ledger)

    def test_current_eligibility_cannot_regress_while_assignments_are_preserved(self):
        from tests.test_unique_eligibility_summary import assessed_summary
        self.assign_remote()
        self.summary, _ = assessed_summary()
        self.assertEqual(self.publish()['status'], 'PUBLISHED')
        for incoming in (assessed_summary('2026-11-19T18:00:00Z')[0], fixtures()[0]):
            self.summary = incoming
            with self.assertRaises(ValueError):
                self.publish()
        saved = json.loads((self.a / 'docs/unique-tasks.json').read_text())
        self.assertEqual(saved['batches'][0]['assignee'], 'seann')
        self.assertEqual(json.loads(self.run_git(self.bare, 'show', 'main:coordination/assignments.json')), self.ledger)

    def test_pending_metadata_commit_cannot_replace_newer_remote_eligibility(self):
        from tests.test_unique_eligibility_summary import assessed_summary
        self.summary, _ = assessed_summary()
        self.assertEqual(self.publish()['status'], 'PUBLISHED')
        for incoming in (assessed_summary('2026-11-19T18:00:00Z')[0], fixtures()[0]):
            for name, raw in render_assets(incoming, self.catalogue, self.ledger, self.at).items():
                (self.a / name).write_bytes(raw)
            self.commit(self.a, 'Owned fixture: stale pending metadata')
            self.summary = incoming
            with self.assertRaises(ValueError):
                self.publish()
            remote = json.loads(self.run_git(self.bare, 'show', 'main:docs/unique-summary.json'))
            self.assertEqual(remote['eligibility']['assessed_at'], '2026-11-19T19:00:00Z')
            self.run_git(self.a, 'reset', '--hard', 'origin/main')

    def test_local_metadata_ahead_and_remote_ledger_rebase_preserves_both(self):
        for name,raw in render_assets(self.summary,self.catalogue,self.ledger,'2026-11-19T00:01:00Z').items():
            (self.a/name).write_bytes(raw)
        self.commit(self.a,'Pending metadata only')
        self.assign_remote()
        self.publish()
        history=self.run_git(self.bare,'log','-3','--format=%s').splitlines()
        self.assertEqual(history[1],'GitHub ledger CAS')
        self.assertEqual(len(history),3)
        self.assertEqual(json.loads((self.a/'docs/unique-tasks.json').read_text())['batches'][0]['assignee'],'seann')
        self.assertEqual(self.run_git(self.a,'show','HEAD:README'),'source unchanged')

    def test_dirty_checkout_and_remote_source_change_hold(self):
        (self.a/'README').write_text('user edit')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual((self.a/'README').read_text(),'user edit')
        self.run_git(self.a,'restore','README')
        (self.b/'README').write_text('remote source edit');self.commit(self.b,'Source edit')
        self.run_git(self.b,'push','origin','main')
        before=self.run_git(self.a,'rev-parse','HEAD')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.run_git(self.a,'rev-parse','HEAD'),before)
        self.assertEqual(self.gh.gets,0)

    def test_hidden_remote_source_change_then_revert_still_hold(self):
        (self.b/'README').write_text('changed');self.commit(self.b,'Source edit')
        (self.b/'README').write_text('source unchanged');self.commit(self.b,'Revert source edit')
        self.assign_remote()
        with self.assertRaises(ValueError):self.publish()

    def test_lost_push_ack_reconciles_without_second_commit_or_push(self):
        self.assign_remote();sync=self.sync();original=sync.git;pushes=[]
        def lose_ack(*args):
            value=original(*args)
            if args[0]=='push':
                pushes.append(args);raise subprocess.CalledProcessError(1,['git','push'])
            return value
        with patch.object(sync,'git',side_effect=lose_ack):result=self.publish(sync)
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(len(pushes),1)
        self.assertEqual(self.run_git(self.bare,'rev-list','--count','main'),'3')
        self.assertEqual(self.publish()['status'],'UNCHANGED')
        self.assertEqual(self.run_git(self.bare,'rev-list','--count','main'),'3')

    def test_ledger_advances_during_push_retains_pending_then_next_poll_reconciles(self):
        # Make an asset update, then a real second writer advances the ledger
        # immediately before the first push. The old view is never pushed.
        sync = self.sync()
        original = sync.git
        pushes = []
        def race(*args):
            if args[0] == 'push' and not pushes:
                pushes.append(args)
                self.assign_remote()
            return original(*args)
        with patch.object(sync, 'git', side_effect=race):
            result = sync.publish(self.summary, self.catalogue, '2026-11-19T00:00:01Z')
        self.assertEqual(result['status'], 'RETRY_PENDING')
        remote_tasks = json.loads(self.run_git(self.bare, 'show', 'main:docs/unique-tasks.json'))
        self.assertIsNone(remote_tasks['batches'][0]['assignee'])
        self.assertEqual(self.publish()['status'], 'PUBLISHED')
        self.assertEqual(self.run_git(self.bare, 'rev-list', '--count', 'main'), '3')
        self.assertEqual(json.loads((self.a/'docs/unique-tasks.json').read_text())['batches'][0]['assignee'], 'seann')

    def test_pending_counts_commit_rebases_with_ledger_and_validates_original_profile(self):
        from tests.test_counts import snapshot
        import counts
        initial = snapshot()
        (self.a/'docs/summary.json').write_text(json.dumps(initial))
        (self.a/'docs/index.html').write_text(counts.render(initial))
        self.commit(self.a, 'Initial counts')
        self.run_git(self.a, 'push', 'origin', 'main')
        self.run_git(self.b, 'pull', '--ff-only')
        incoming = copy.deepcopy(initial)
        incoming['audit_utc'] = '2026-11-19T00:00:00+00:00'
        (self.a/'docs/summary.json').write_text(json.dumps(incoming))
        (self.a/'docs/index.html').write_text(counts.render(incoming))
        self.commit(self.a, 'Pending validated counts')
        self.assign_remote()
        self.publish()
        self.assertEqual(json.loads(self.run_git(self.bare, 'show', 'main:docs/summary.json')), incoming)
        self.assertEqual(self.run_git(self.bare, 'rev-list', '--count', 'main'), '4')

    def test_stale_timestamp_or_symlink_asset_hold_without_commit(self):
        (self.a/'docs/unique-tasks.json').unlink()
        (self.a/'docs/unique-tasks.json').symlink_to(self.a/'README')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.run_git(self.bare, 'rev-list', '--count', 'main'), '1')

    def test_wrong_origin_unreviewed_pending_source_or_multiple_commits_hold(self):
        with self.assertRaises(ValueError):
            Synchronizer(self.a,self.gh,expected_origins=('not-this-repository',)).publish(self.summary,self.catalogue,self.at)
        (self.a/'README').write_text('local source');self.commit(self.a,'Unpushed source')
        with self.assertRaises(ValueError):self.publish()

    def test_stable_timestamp_uses_authority_not_poll_time(self):
        self.assertEqual(stable_generated_at(self.ledger,self.at),self.at)
        self.assign_remote()
        self.assertEqual(stable_generated_at(self.ledger,self.at),'2026-11-19T01:00:00Z')
        with self.assertRaises(ValueError):stable_generated_at(self.ledger,'invalid')

    def test_ledger_changes_between_fetch_and_get_holds_without_asset_write(self):
        original = self.gh.api
        def changed(*args, **kwargs):
            self.assign_remote()
            return original(*args, **kwargs)
        before = self.run_git(self.a, 'rev-parse', 'HEAD')
        with patch.object(self.gh, 'api', side_effect=changed), self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.run_git(self.a, 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.run_git(self.a, 'status', '--porcelain'), '')

    def test_arbitrary_pending_html_or_two_pending_commits_hold(self):
        (self.a/'docs/unique.html').write_text('<html>private report</html>')
        self.commit(self.a, 'Unapproved HTML')
        with self.assertRaises(ValueError):self.publish()
        for name, raw in render_assets(self.summary,self.catalogue,self.ledger,self.at).items():
            (self.a/name).write_bytes(raw)
        self.commit(self.a, 'Second pending commit')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.run_git(self.bare, 'rev-list', '--count', 'main'), '1')

    def test_native_private_field_cannot_reach_generated_commit(self):
        self.catalogue['batches'][0]['private_path']='/private/native'
        before=self.run_git(self.a,'rev-parse','HEAD')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.run_git(self.a,'rev-parse','HEAD'),before)
        self.assertEqual(self.run_git(self.a,'status','--porcelain'),'')


if __name__=='__main__':unittest.main()

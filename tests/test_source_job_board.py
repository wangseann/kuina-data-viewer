import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import acquisition
import source_job_board as board
from coordination.source_jobs import confirm, public_definition, catalogue_rows
from coordination.assignment_publication import task_snapshot
from test_unique_dashboard import fixtures


class SourceBoardTests(unittest.TestCase):
    def setUp(self):
        self.sources=json.loads((Path(__file__).resolve().parents[1]/'docs/acquisition-sources.json').read_text())
        self.manifest=confirm(self.sources,['crypto-spot-kraken'],'a'*64)
        self.definitions=dict(schema=board.DEFINITION_SCHEMA,jobs=[public_definition(self.manifest['jobs'][0])])
        self.catalogue=dict(schema='kuina-public-assignment-catalogue-v1',
                            generation='a'*64,batches=catalogue_rows(self.manifest))
        self.ledger=dict(schema='kuina-github-assignments-v1',migration=dict(
            complete=True,source_sha256='a'*64,catalogue_generation='a'*64),assignments={},receipts={})
        self.at=self.manifest['jobs'][0]['confirmed_at'].replace('+00:00','Z')

    def snapshot(self):
        return board.snapshot(self.definitions,self.sources,self.catalogue,self.ledger,self.at)

    def test_closed_projection_keeps_new_jobs_out_of_inventory_counts(self):
        result=self.snapshot()
        self.assertEqual(result['jobs'][0]['state'],'open')
        summary,_=fixtures()
        snapshot=task_snapshot(summary,self.catalogue,self.ledger,self.at)
        self.assertEqual(snapshot['batches'],[])
        for key,value in [('note','PRIVATE'),('uid',123),('path','/private/data')]:
            bad=copy.deepcopy(result);bad['jobs'][0][key]=value
            with self.assertRaises(ValueError):board.validate_snapshot(bad)
        bad=copy.deepcopy(self.catalogue);bad['batches'][0]['definition_sha256']='0'*64
        with self.assertRaises(ValueError):board.snapshot(self.definitions,self.sources,bad,self.ledger,self.at)

    def test_escaped_payload_and_rebuild_preserve_the_job_board(self):
        jobs=self.snapshot();jobs['jobs'][0]['provider']='</script><img src=x onerror=alert(1)>'
        page=acquisition.render(self.sources,jobs)
        payload=re.search(r'<script id="source-jobs-data" type="application/json">(.*?)</script>',page).group(1)
        self.assertNotIn('</script>',payload)
        self.assertEqual(json.loads(payload),jobs)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'source-jobs.json').write_text(json.dumps(jobs))
            acquisition.build(self.sources,folder)
            self.assertIn('source-jobs-data',(Path(folder)/'sources.html').read_text())

    def test_browser_claim_commands_progress_and_stale_refresh(self):
        jobs=self.snapshot()
        for suffix,state,stage,person,issue in [('reserved','in_progress','reserved','seann',42),
                                               ('finished','finished','finished','juan',43)]:
            item=copy.deepcopy(jobs['jobs'][0]);item.update(id='unique-source-'+suffix,
                state=state,stage=stage,assignee=person,assignment_issue=issue)
            jobs['jobs'].append(item)
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'board.js';script.write_text(board.SCRIPT)
            data=Path(folder)/'snapshot.json';data.write_text(json.dumps(jobs))
            subprocess.run(['node',str(Path(__file__).with_suffix('.js')),str(script),str(data)],
                           check=True,capture_output=True)


if __name__=='__main__':unittest.main()

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from failure_codes import visible_counts
from series_names import export_names, validate_names, counts_digest
from test_failure_colours import snapshot


def record(identity,label,mask,field='close'):
    reasons={1:'hourly_gaps',2:'coarse_resolution',4:'short_history',8:'calendar_unverified'}
    return dict(id=identity*64,label=label,variable=field,source='Example provider',nativeSeconds=60,
                decision='INELIGIBLE' if mask else 'ELIGIBLE',
                checks=[dict(status='FAIL',reason=reason)for bit,reason in reasons.items()if mask&bit],
                sourceReferences=['/private/never-publish'],preview={'values':[123456789]})


class NamesTests(unittest.TestCase):
    def build(self,records):
        root=Path(self.temp.name);package=root/'package';package.mkdir()
        (package/'catalogue').mkdir()
        references=[]
        for offset in range(0,len(records),2500):
            raw=gzip.compress(json.dumps(dict(schema='kuina-series-page-v1',datasetId='dataset',series=records[offset:offset+2500])).encode())
            relative='catalogue/page-'+str(offset)+'.json.gz'
            (package/relative).write_bytes(raw)
            references.append(dict(path=relative,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),rows=len(records[offset:offset+2500])))
        summary=snapshot()
        manifest=dict(schema='kuina-inspection-v1',auditUtc=summary['audit_utc'],assessmentUtc=summary['assessment_utc'],
                      windowStart='2024-10-01',windowEnd='2026-10-01',catalogueRows=len(records),
                      requirements=dict(maxNativeSeconds=900,minHistoryYears=2),
                      datasets=[dict(id='dataset',type='stocks',series=len(records),eligible=1,pages=references)])
        content=json.dumps(manifest).encode();(package/'inspection-manifest.json').write_bytes(content)
        return package,summary,hashlib.sha256(content).hexdigest()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.records=[record('a','XRP-USD',0),record('b','BTC/USD',1),record('c','Name <script>',2),record('d','Gold',7)]

    def test_named_tiles_reconcile_each_mask_and_never_export_values_or_private_refs(self):
        package,summary,sha=self.build(self.records)
        result,proof=export_names(package,summary,sha)
        self.assertEqual(result['counts_sha256'],counts_digest(summary))
        self.assertEqual(result['catalogue_sha256'],sha)
        selected=next(row['series']for row in result['types']if row['id']=='stocks')
        self.assertEqual([row['mask']for row in selected],[0,1,2,7])
        self.assertEqual(selected[0]['label'],'XRP-USD')
        self.assertIn('BTC/USD',[row['label']for row in selected])
        self.assertNotIn('123456789',json.dumps(result));self.assertNotIn('/private/',json.dumps(result))
        self.assertEqual(proof['catalogue_records'],4)
        validate_names(result,summary)

    def test_final_counts_mismatch_and_changed_page_fail_closed(self):
        package,summary,sha=self.build(self.records)
        summary['types'][0]['confirmed_series']=2
        with self.assertRaises(ValueError):export_names(package,summary,sha)
        (package/'catalogue/page-0.json.gz').write_bytes(b'changed')
        with self.assertRaises(ValueError):export_names(package,snapshot(),sha)

    def test_path_metadata_is_not_published_as_display_name(self):
        self.records[1]['label']='name=/datashare/A121/private/file'
        self.records[2]['source']='https://example.com/private'
        package,summary,sha=self.build(self.records)
        result,_=export_names(package,summary,sha)
        self.assertNotIn('/datashare/',json.dumps(result));self.assertNotIn('https://',json.dumps(result))
        self.assertIn('not available',json.dumps(result))

    def test_labels_reject_private_paths_and_controls_but_preserve_real_symbols(self):
        from series_names import safe_text,native_interval
        for label in ('name=/datashare/private/x','unit=/unlisted/private/path','s3://bucket/key','a\x85b','   '):
            self.assertFalse(safe_text(label,400),label)
        for label in ('BTC/USD','/ES','XRP-USD'):
            self.assertTrue(safe_text(label,400),label)
        self.assertEqual(native_interval(31557600),31557600)
        self.assertIsNone(native_interval(-1))

    def test_index_rejects_extra_payload_wrong_digest_duplicate_identity_and_mask(self):
        package,summary,sha=self.build(self.records)
        result,_=export_names(package,summary,sha)
        row=result['types'][0]['series'][0]
        for key,value in [('observations',[1]),('mask',9),('id','wrong')]:
            previous=dict(row);row[key]=value
            with self.assertRaises(ValueError):validate_names(result,summary)
            row.clear();row.update(previous)
        result['counts_sha256']='0'*64
        with self.assertRaises(ValueError):validate_names(result,summary)

    def test_all_records_checked_but_names_are_bounded_by_visible_quota(self):
        records=[record('a','Eligible',0)]
        for n in range(4002):
            item=record('b','Unit '+str(n),1)
            item['id']=hashlib.sha256(str(n).encode()).hexdigest()
            records.append(item)
        package,summary,_=self.build(records)
        row=summary['types'][0]
        row.update(excluded_series=4002,excluded_measured=4002,
                   issues=[dict(id='hourly_gaps',count=4002)],failure_masks=[dict(mask=1,count=4002)])
        manifest_path=package/'inspection-manifest.json'
        sha=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        output,proof=export_names(package,summary,sha)
        self.assertEqual(proof['catalogue_records'],4003)
        self.assertEqual(proof['selected_records'],4001)
        # Corrupt the last, unselected record while keeping its page hash current.
        manifest=json.loads(manifest_path.read_text());reference=manifest['datasets'][0]['pages'][-1]
        page=json.loads(gzip.decompress((package/reference['path']).read_bytes()))
        page['series'][-1]['checks']=[]
        raw=gzip.compress(json.dumps(page).encode());(package/reference['path']).write_bytes(raw)
        reference.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        raw=json.dumps(manifest).encode();manifest_path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'decision and failure mask'):
            export_names(package,summary,hashlib.sha256(raw).hexdigest())

if __name__=='__main__':unittest.main()

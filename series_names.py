"""Export a name-only, hash-bound sample from an existing verified audit catalogue.

No source observations are opened and no audit decision is recomputed.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re

from counts import IDS, validate
from failure_codes import classify_reasons, visible_counts

MAX_PAGE = 32 * 1024**2
MAX_INPUT = 4 * 1024**3
MAX_OUTPUT = 32 * 1024**2
MAX_COMPRESSED_OUTPUT = 8 * 1024**2
PRIVATE = re.compile(r'/(?:datashare|flash|bucket|Users|home|private|mnt|scratch|tmp|var)/|(?:^|[\s=,:;])/[^\s/]*/|[A-Za-z][A-Za-z0-9+.-]*://|[A-Za-z]:\\',re.I)
HEX = re.compile(r'[0-9a-f]{64}')
FIELDS = {'id','label','variable','source','native_seconds','mask'}


def require(condition,message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def counts_digest(summary):
    validate(summary)
    return hashlib.sha256(canonical(summary)).hexdigest()


def quotas(summary):
    return {row['id']:{0:min(row['confirmed_series'],20000),**visible_counts(row['failure_masks'])}
            for row in summary['types']}


def safe_text(value,maximum):
    return (isinstance(value,str) and bool(value.strip()) and 0<len(value)<=maximum and
            not PRIVATE.search(value) and not any(ord(c)<32 or 127<=ord(c)<=159 for c in value))


def native_interval(value):
    if type(value)in (int,float) and math.isfinite(value) and 0<value<=9007199254740991:
        return value
    return None


def display_text(value,maximum):
    if not safe_text(value,maximum):
        return 'Name not available for public display'
    return value


def validate_names(data,summary):
    validate(summary)
    require(isinstance(data,dict) and set(data)=={'schema','audit_utc','assessment_utc','counts_sha256','catalogue_sha256','types'},'Unexpected name-index fields')
    require(type(data['schema'])is int and data['schema']==1,'Unsupported name-index schema')
    require(data['audit_utc']==summary['audit_utc'] and data['assessment_utc']==summary['assessment_utc'] and
            data['counts_sha256']==counts_digest(summary),'Name index belongs to another counts snapshot')
    require(isinstance(data['catalogue_sha256'],str) and HEX.fullmatch(data['catalogue_sha256']),'Invalid catalogue identity')
    require(isinstance(data['types'],list) and len(data['types'])==len(IDS),'Invalid name-index categories')
    expected=quotas(summary);seen_types=set();seen_ids=set()
    for group in data['types']:
        require(isinstance(group,dict) and set(group)=={'id','series'} and group['id']in IDS and
                group['id']not in seen_types and isinstance(group['series'],list),'Invalid name-index group')
        seen_types.add(group['id']);actual=Counter();previous_mask=0
        for item in group['series']:
            require(isinstance(item,dict) and set(item)==FIELDS,'Unexpected series-name fields')
            identity=item['id']
            require(isinstance(identity,str) and HEX.fullmatch(identity) and identity not in seen_ids,'Invalid or repeated series identity')
            seen_ids.add(identity)
            require(safe_text(item['label'],400) and safe_text(item['variable'],128) and safe_text(item['source'],128),'Unsafe display text')
            seconds=item['native_seconds']
            require(seconds is None or type(seconds)in (int,float) and math.isfinite(seconds) and 0<seconds<=9007199254740991,'Invalid native interval')
            require(type(item['mask'])is int and 0<=item['mask']<=15,'Invalid failure mask')
            require(item['mask']>=previous_mask,'Named sample masks are not ordered')
            previous_mask=item['mask']
            actual[item['mask']]+=1
        require(dict(actual)=={mask:count for mask,count in expected[group['id']].items()if count},'Named sample does not match displayed mask counts')
    require(len(canonical(data))<=MAX_OUTPUT,'Name index exceeds output bound')
    return data


def regular_path(root,relative):
    require(isinstance(relative,str) and relative and not relative.startswith('/') and
            all(part not in ('','..','.')for part in relative.split('/')) and '\\'not in relative,'Unsafe catalogue path')
    current=root
    for part in relative.split('/'):
        current=current/part
        require(not current.is_symlink(),'Catalogue symlinks are not followed')
    require(current.is_file(),'Catalogue file missing')
    return current


def export_names(package,summary,manifest_sha):
    validate(summary)
    require(summary['schema']==4,'Names require the current 15-minute audit profile')
    require(package.is_dir() and not package.is_symlink(),'Invalid catalogue package')
    manifest_path=regular_path(package,'inspection-manifest.json')
    require(manifest_path.stat().st_size<=1024**2,'Catalogue manifest exceeds bound')
    raw=manifest_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==manifest_sha,'Catalogue manifest hash mismatch')
    manifest=json.loads(raw)
    require(manifest['schema']=='kuina-inspection-v1' and manifest['auditUtc']==summary['audit_utc'] and
            manifest['assessmentUtc']==summary['assessment_utc'] and manifest['requirements']==dict(maxNativeSeconds=900,minHistoryYears=2) and
            manifest['windowStart']=='2024-10-01' and manifest['windowEnd']=='2026-10-01','Catalogue audit/profile mismatch')
    remaining=quotas(summary)
    selected={identifier:[]for identifier in IDS};totals={identifier:Counter()for identifier in IDS}
    rows=0;input_bytes=0;page_count=0
    datasets=manifest['datasets']
    require(isinstance(datasets,list) and len(datasets)<=200,'Catalogue dataset count exceeds bound')
    for dataset in datasets:
        category=dataset['type'];require(category in IDS,'Unknown catalogue category')
        dataset_rows=0;dataset_eligible=0
        for reference in dataset['pages']:
            size=reference['bytes']
            require(type(size)is int and 0<size<=MAX_PAGE,'Catalogue page exceeds bound')
            input_bytes+=size;require(input_bytes<=MAX_INPUT,'Catalogue read budget exceeded')
            path=regular_path(package,reference['path'])
            require(path.stat().st_size==size,'Catalogue page size changed')
            raw=path.read_bytes()
            require(hashlib.sha256(raw).hexdigest()==reference['sha256'],'Catalogue page hash mismatch')
            with gzip.GzipFile(fileobj=io.BytesIO(raw))as stream:
                unpacked=stream.read(MAX_PAGE+1)
            require(len(unpacked)<=MAX_PAGE,'Decompressed catalogue page exceeds bound')
            page=json.loads(unpacked);records=page['series']
            require(page['schema']=='kuina-series-page-v1' and page['datasetId']==dataset['id'] and
                    isinstance(records,list) and len(records)==reference['rows'] and len(records)<=2500,'Catalogue page identity/count mismatch')
            for record in records:
                decision=record['decision']
                require(decision in ('ELIGIBLE','INELIGIBLE'),'Unknown saved audit decision')
                reasons=[check['reason']for check in record['checks']if check['status']=='FAIL']
                mask=classify_reasons(reasons)
                require((decision=='ELIGIBLE')==(mask==0),'Saved decision and failure mask disagree')
                totals[category][mask]+=1;dataset_rows+=1;rows+=1;dataset_eligible+=mask==0
                if remaining[category].get(mask,0)<=0:
                    continue
                selected[category].append(dict(id=record['id'],label=display_text(record['label'],400),
                    variable=display_text(record['variable'],128),source=display_text(record['source'],128),
                    native_seconds=native_interval(record['nativeSeconds']),mask=mask))
                remaining[category][mask]-=1
            page_count+=1
        require(dataset_rows==dataset['series'] and dataset_eligible==dataset['eligible'],'Catalogue dataset totals mismatch')
    require(rows==manifest['catalogueRows'],'Catalogue row count mismatch')
    for row in summary['types']:
        expected={0:row['confirmed_series'],**{b['mask']:b['count']for b in row['failure_masks']}}
        require(dict(totals[row['id']])=={mask:count for mask,count in expected.items()if count},'Full catalogue counts differ from public audit: '+row['id'])
    output=dict(schema=1,audit_utc=summary['audit_utc'],assessment_utc=summary['assessment_utc'],
                counts_sha256=counts_digest(summary),catalogue_sha256=manifest_sha,
                types=[dict(id=identifier,series=sorted(selected[identifier],key=lambda item:(item['mask'],item['id'])))for identifier in IDS])
    validate_names(output,summary)
    proof=dict(status='SERIES_NAMES_VERIFIED',catalogue_records=rows,catalogue_pages=page_count,
               input_bytes=input_bytes,selected_records=sum(len(group['series'])for group in output['types']),
               catalogue_sha256=manifest_sha,counts_sha256=output['counts_sha256'],
               observations_read=False,dataset_changes=False)
    return output,proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--counts',type=Path,required=True)
    parser.add_argument('--manifest-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),'Use a fresh output directory; never overwrite a retained extraction')
    data,proof=export_names(args.package,json.loads(args.counts.read_text()),args.manifest_sha256)
    raw=canonical(data);compressed=gzip.compress(raw,compresslevel=6,mtime=0)
    require(len(compressed)<=MAX_COMPRESSED_OUTPUT,'Compressed name-index exceeds retrieval bound')
    args.output.mkdir()
    (args.output/'series-names.json.gz').write_bytes(compressed)
    proof.update(json_bytes=len(raw),compressed_bytes=len(compressed),json_sha256=hashlib.sha256(raw).hexdigest(),
                 compressed_sha256=hashlib.sha256(compressed).hexdigest())
    (args.output/'provenance.json').write_bytes(canonical(proof)+b'\n')
    print(json.dumps(proof))

if __name__=='__main__':main()

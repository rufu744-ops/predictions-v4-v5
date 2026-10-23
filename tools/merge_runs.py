"""Merge matrix outputs once, then the workflow performs a single git write."""
import argparse
from pathlib import Path,PurePosixPath
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.logs import digest,bundles
from common.exchange import exclusive_bytes


def merge(source,destination):
    source,destination=Path(source),Path(destination);planned={}
    manifests=sorted(source.glob('*/run_manifest.json'))
    if not manifests:raise ValueError('No matrix run outputs downloaded')
    for manifest in manifests:
        meta=json.loads(manifest.read_text());version,market=meta['version'],meta['market']
        if version not in ['v4a','v4b'] or market not in ['JP','US']:raise ValueError('Unexpected matrix scope')
        base=manifest.parent
        for entry in meta['files']:
            ref=entry['path'];parts=PurePosixPath(ref).parts
            log=(len(parts)==4 and parts[0] in ['predictions','evaluations'] and parts[1:3]==(version,market) and PurePosixPath(ref).suffix in ['.csv','.json'])
            status=ref==f'output/status/{version}/{market}.json'
            if not (log or status) or '\\' in ref or '..' in parts:raise ValueError('Unexpected matrix output path')
            path=base/ref
            if base.resolve() not in path.resolve().parents or path.is_symlink() or digest(path)!=entry['sha256']:raise ValueError('Matrix output integrity failure')
            target=destination/ref
            if destination.resolve() not in target.resolve().parents:raise ValueError('Destination escapes checkout')
            data=path.read_bytes()
            if ref in planned and planned[ref][0]!=data:raise ValueError('Conflicting matrix output')
            if not status and target.exists() and target.read_bytes()!=data:raise ValueError('Immutable local history conflict')
            planned[ref]=(data,status)
        for family in ['predictions','evaluations']:
            for _ in bundles(base/family/version/market):pass
    for ref,(data,status) in planned.items():
        target=destination/ref
        if status:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        else:exclusive_bytes(target,data)
    return len(planned)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--destination',default=Path.cwd(),type=Path);a=p.parse_args();print(f'Merged {merge(a.source,a.destination)} files')

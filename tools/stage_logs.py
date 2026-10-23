"""Stage only this matrix member's private logs; never features or model states."""
import argparse
from pathlib import Path
import sys,json,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.logs import bundles,digest
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--model',required=True,choices=['a','b']);p.add_argument('--market',required=True,choices=['JP','US']);p.add_argument('--destination',required=True,type=Path);a=p.parse_args()
    ROOT=a.root.resolve();version='v4'+a.model;files=[]
    for family in ['predictions','evaluations']:
        for path,_ in bundles(ROOT/family/version/a.market):
            for source in [path,path.with_suffix('.json')]:
                ref=source.relative_to(ROOT);target=a.destination/ref;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
                files.append(dict(path=ref.as_posix(),sha256=digest(target)))
    status=ROOT/'output/status'/version/(a.market+'.json')
    if status.exists():
        ref=status.relative_to(ROOT);target=a.destination/ref;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(status,target)
        files.append(dict(path=ref.as_posix(),sha256=digest(target)))
    a.destination.mkdir(parents=True,exist_ok=True)
    (a.destination/'run_manifest.json').write_text(json.dumps(dict(version=version,market=a.market,files=files),indent=2))

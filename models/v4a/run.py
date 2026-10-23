import argparse
import json
from pathlib import Path
from v4a.data import load
from v4a.engine import Settings,run
from v4a.storage import evaluate
from v4a.exchange import export_results
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    p=argparse.ArgumentParser(description='V4-A: Kalman regression, monthly ML noise calibration')
    p.add_argument('--market',choices=['JP','US'],required=True)
    p.add_argument('--input',type=Path,help='V3 feature export folder; default inputs/MARKET')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--horizons',nargs='+',type=int,choices=[1,5,20],default=[1,5,20])
    p.add_argument('--train-sessions',type=int,default=1260)
    p.add_argument('--min-observations',type=int,default=30)
    p.add_argument('--min-coverage',type=float,default=.95)
    p.add_argument('--information-set',default='V3_FEATURES')
    p.add_argument('--light',action='store_true',help='ML iterations=24; model/data/horizons unchanged')
    p.add_argument('--as-of',help='Research only: writes output/research, never the live exchange')
    p.add_argument('--evaluate-only',action='store_true')
    a=p.parse_args()
    data=load(a.input or a.root/'inputs'/a.market,a.market)
    if data.manifest.get('synthetic',False): p.error('Synthetic inputs forbidden here; use demo.py')
    root=a.root/'output/research' if a.as_of else a.root
    settings=Settings(horizons=tuple(a.horizons),train_sessions=a.train_sessions,
        min_observations=a.min_observations,min_coverage=a.min_coverage,
        maxiter=24 if a.light else 32,information_set=a.information_set)
    if a.as_of and a.evaluate_only: p.error('--as-of cannot be combined with --evaluate-only')
    ev=evaluate(data,root)
    print(json.dumps(dict(evaluation_file=str(ev) if ev else None)))
    if not a.evaluate_only: print(json.dumps(run(data,root,settings,a.as_of)))


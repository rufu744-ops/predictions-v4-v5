import argparse
import json
from pathlib import Path
from v4b.data import load
from v4b.engine import Settings,run
from v4b.storage import evaluate
from v4b.exchange import export_results
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    p=argparse.ArgumentParser(description='V4-B: Bayesian Kalman regression, monthly posterior quadrature')
    p.add_argument('--market',choices=['JP','US'],required=True)
    p.add_argument('--input',type=Path,help='V3 feature export folder; default inputs/MARKET')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--horizons',nargs='+',type=int,choices=[1,5,20],default=[1,5,20])
    p.add_argument('--train-sessions',type=int,default=1260)
    p.add_argument('--min-observations',type=int,default=30)
    p.add_argument('--min-coverage',type=float,default=.95)
    p.add_argument('--information-set',default='V3_FEATURES')
    p.add_argument('--light',action='store_true',help='Grid 33..129 and tolerance .01; data/features/horizons unchanged')
    p.add_argument('--grid-points',type=int,default=65)
    p.add_argument('--max-grid-points',type=int,default=257)
    p.add_argument('--quadrature-tolerance',type=float,default=.002)
    p.add_argument('--prior-width-sd',type=float,default=6.)
    p.add_argument('--log-ratio-mean',type=float,default=-9.210340371976184)
    p.add_argument('--log-ratio-sd',type=float,default=2.)
    p.add_argument('--variance-shape',type=float,default=2.5)
    p.add_argument('--variance-scale',type=float,default=1.5e-4)
    p.add_argument('--as-of',help='Research only: writes output/research, never the live exchange')
    p.add_argument('--evaluate-only',action='store_true')
    a=p.parse_args()
    data=load(a.input or a.root/'inputs'/a.market,a.market)
    if data.manifest.get('synthetic',False): p.error('Synthetic inputs forbidden here; use demo.py')
    root=a.root/'output/research' if a.as_of else a.root
    settings=Settings(horizons=tuple(a.horizons),train_sessions=a.train_sessions,
        min_observations=a.min_observations,min_coverage=a.min_coverage,
        grid_points=33 if a.light else a.grid_points,
        max_grid_points=129 if a.light else a.max_grid_points,
        quadrature_tolerance=.01 if a.light else a.quadrature_tolerance,
        log_ratio_mean=a.log_ratio_mean,log_ratio_sd=a.log_ratio_sd,prior_width_sd=a.prior_width_sd,
        variance_shape=a.variance_shape,variance_scale=a.variance_scale,information_set=a.information_set)
    if a.as_of and a.evaluate_only: p.error('--as-of cannot be combined with --evaluate-only')
    ev=evaluate(data,root)
    print(json.dumps(dict(evaluation_file=str(ev) if ev else None)))
    if not a.evaluate_only: print(json.dumps(run(data,root,settings,a.as_of)))


"""One repository; isolated A/B Python processes; one combined results export."""
import argparse
from pathlib import Path
import subprocess
import sys
from common.exchange import export_results
ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',choices=['a','b','both'],default='both')
    p.add_argument('--market',type=str.upper,choices=['JP','US','BOTH'],required=True)
    p.add_argument('--input',type=Path)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--light',action='store_true')
    p.add_argument('--demo',action='store_true')
    p.add_argument('--demo-tickers',type=int,default=1)
    args,extra=p.parse_known_args()
    choices=['a','b'] if args.model=='both' else [args.model]
    markets=['JP','US'] if args.market=='BOTH' else [args.market]
    running=[]
    for market in markets:
        for model in choices:
            path=ROOT/'models'/('v4'+model)
            if args.demo:
                if extra:p.error('Extra live-model flags cannot be used in demo mode')
                command=[sys.executable,str(path/'demo.py'),'--market',market,'--tickers',str(args.demo_tickers)]
            else:
                input_dir=((args.input/market if args.market=='BOTH' else args.input) if args.input else args.root/'inputs'/market).resolve()
                command=[sys.executable,str(path/'run.py'),'--market',market,'--input',str(input_dir),'--root',str(args.root.resolve()),*extra]
                if args.light:command.append('--light')
            running.append(subprocess.Popen(command,cwd=path))
    codes=[process.wait() for process in running]
    # Even if one new forecast fails, already-completed native evaluations are retained.
    if not args.demo and '--as-of' not in extra:
        print(f'Combined results: {export_results(args.root,args.root/"exchange")} bundles',flush=True)
    return 1 if any(codes) else 0


if __name__=='__main__':raise SystemExit(main())

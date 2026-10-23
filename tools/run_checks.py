import argparse
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',choices=['a','b','both'],default='both');a=p.parse_args()
    models=['a','b'] if a.model=='both' else [a.model]
    for model in models:
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT/'models'/('v4'+model),check=True)
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,check=True)

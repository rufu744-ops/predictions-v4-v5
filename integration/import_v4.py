import argparse
from pathlib import Path
from exchange_reader import import_results
if __name__=='__main__':
    p=argparse.ArgumentParser(description='Import V4-A/B results into the existing dashboard')
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--destination',default=Path.cwd(),type=Path)
    a=p.parse_args();print(f'Imported {import_results(a.source,a.destination)} result bundles')

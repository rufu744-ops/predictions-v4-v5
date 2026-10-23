"""Adapter for a V3 panel CSV; requires real availability timestamps and exchange sessions."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'models/v4a'))
import pandas as pd
from v4a.data import write_input
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--panel',required=True,type=Path)
    p.add_argument('--sessions',required=True,type=Path)
    p.add_argument('--universe',required=True,type=Path,help='CSV with ticker column, current official universe')
    p.add_argument('--market',required=True,choices=['JP','US'])
    p.add_argument('--features',required=True,nargs='+',help='Exact V3 feature columns to inherit')
    p.add_argument('--close-column',default='Close',help='MUST be split/dividend adjusted')
    p.add_argument('--available-column',default='available_at_utc',help='Maximum availability time of row inputs')
    p.add_argument('--source',required=True,help='V3 exporter version / audit identifier')
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    panel=pd.read_csv(a.panel,dtype={'ticker':str})
    universe=pd.read_csv(a.universe,dtype={'ticker':str})
    sessions=pd.read_csv(a.sessions)
    if not a.features or len(set(a.features))!=len(a.features):p.error('Feature columns must be unique')
    forbidden={'ticker','date',a.close_column,a.available_column}
    if set(a.features)&forbidden:p.error('Identity, timestamp and close columns cannot be features')
    renaming={c:'f_'+c if not c.startswith('f_') else c for c in a.features}
    if len(set(renaming.values()))!=len(renaming):p.error('Feature renaming collision')
    frame=panel[['date','ticker',a.available_column,*a.features]].rename(columns={a.available_column:'available_at_utc',**renaming})
    price=panel[['date','ticker',a.close_column]].rename(columns={a.close_column:'adjusted_close'})
    data=write_input(a.output,a.market,sessions,price,frame,list(renaming.values()),
        universe.ticker.tolist(),a.source,False)
    print(f'Validated {len(data.features)} point-in-time feature rows for {len(universe)} expected stocks')

"""Offline synthetic demonstration, isolated from live logs and result exchange."""
import argparse
from pathlib import Path
import json
import numpy as np
import pandas as pd
from v4a.data import write_input
from v4a.engine import Settings,run
from v4a.storage import evaluate
ROOT=Path(__file__).resolve().parent


def make_input(folder,market='US',n_tickers=4,n_sessions=840):
    rng=np.random.default_rng(20261024)
    dates=pd.bdate_range('2021-01-04',periods=n_sessions+40).strftime('%Y-%m-%d')
    hour='06:00:00Z' if market=='JP' else '21:00:00Z'
    sessions=pd.DataFrame(dict(date=dates,close_at_utc=[d+'T'+hour for d in dates]))
    tickers=[f'DEMO{i:03d}' for i in range(n_tickers)]
    features=[];prices=[]
    for ticker in tickers:
        signals=rng.normal(size=(n_sessions,3))
        beta=np.cumsum(rng.normal(0,.00005,(n_sessions,3)),axis=0)+np.array([.001,-.001,.0004])
        returns=np.zeros(n_sessions)
        returns[1:]=np.einsum('ij,ij->i',signals[:-1],beta[1:])+rng.normal(0,.008,n_sessions-1)
        close=100*np.cumprod(1+returns)
        prices.append(pd.DataFrame(dict(ticker=ticker,date=dates[:n_sessions],adjusted_close=close)))
        f=pd.DataFrame(signals,columns=['f_momentum','f_macro','f_roe'])
        f['ticker']=ticker;f['date']=dates[:n_sessions];f['available_at_utc']=[d+'T'+hour for d in dates[:n_sessions]]
        features.append(f)
    return write_input(folder,market,sessions,pd.concat(prices,ignore_index=True),
        pd.concat(features,ignore_index=True),['f_momentum','f_macro','f_roe'],tickers,
        source='SYNTHETIC_DEMO: weekday mock calendar, not real exchange sessions',synthetic=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--market',choices=['JP','US','BOTH'],default='BOTH')
    p.add_argument('--tickers',type=int,default=4)
    a=p.parse_args()
    for market in ['JP','US'] if a.market=='BOTH' else [a.market]:
        root=ROOT/'output/demo'/market
        data=make_input(root/'input',market,a.tickers)
        for idx in [790,791]:
            result=run(data,root,Settings(maxiter=24),as_of=data.sessions.date.iloc[idx],now=pd.Timestamp(data.sessions.close_at_utc.iloc[idx]))
            print('SYNTHETIC',market,json.dumps(result))
        print('SYNTHETIC',market,'evaluation:',evaluate(data,root,now=pd.Timestamp(data.sessions.close_at_utc.iloc[835])))

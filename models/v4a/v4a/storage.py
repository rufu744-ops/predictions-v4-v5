"""Append-only forecasts and evaluation logs. JSON manifest is the commit marker."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import uuid
import numpy as np
import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundles(folder):
    for manifest in sorted(Path(folder).glob('*.json')):
        meta=json.loads(manifest.read_text())
        path=manifest.with_suffix('.csv')
        if meta.get('csv_file')!=path.name or not path.exists() or digest(path)!=meta['csv_sha256']:
            raise ValueError(f'Changed/incomplete log: {manifest.name}')
        yield path,meta


def save(frame,folder,stem,meta):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{stem}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}.csv'
    frame.to_csv(path,index=False,mode='x')
    obj=dict(meta,csv_file=path.name,csv_sha256=digest(path))
    with path.with_suffix('.json').open('x') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False)
    return path


def save_prediction(frame,folder,meta):
    folder=Path(folder)
    stem=meta['data_last_observation_date']+'_v4a'
    # Reserve a unique path before constructing stable IDs that include that path.
    name=f'{stem}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}.csv'
    path=folder/name
    root=folder.parents[2]
    ref=path.relative_to(root).as_posix()
    z=frame.copy();z['source_forecast_file']=ref
    z['forecast_id']=[hashlib.sha256('|'.join(map(str,[ref,r.ticker,r.horizon_sessions,r.information_set,r.model])).encode()).hexdigest() for r in z.itertuples()]
    folder.mkdir(parents=True,exist_ok=True)
    z.to_csv(path,index=False,mode='x')
    with path.with_suffix('.json').open('x') as f:
        json.dump(dict(meta,csv_file=path.name,csv_sha256=digest(path)),f,indent=2,allow_nan=False)
    return path


def evaluate(dataset,root,now=None):
    root=Path(root)
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    eligible=set(dataset.sessions.loc[dataset.sessions.close_at_utc<=now,'date'])
    price=dataset.prices[dataset.prices.date.isin(eligible)].set_index(['ticker','date']).adjusted_close
    done=set()
    folder=root/'evaluations/v4a'/dataset.market
    for p,_ in bundles(folder):
        e=pd.read_csv(p,dtype={'ticker':str})
        done.update(e.forecast_id)
    rows=[]
    for p,meta in bundles(root/'predictions/v4a'/dataset.market):
        if bool(meta.get('synthetic',False))!=bool(dataset.manifest.get('synthetic',False)):
            raise ValueError('Synthetic/real evaluation mixing is forbidden')
        z=pd.read_csv(p,dtype={'ticker':str})
        ref=p.relative_to(root).as_posix()
        for r in z.itertuples():
            if r.forecast_id in done: continue
            a=price.get((r.ticker,r.data_last_observation_date))
            b=price.get((r.ticker,r.forecast_for_session_date))
            if a is None or b is None or not np.isfinite(a) or not np.isfinite(b): continue
            actual=float(b/a-1)
            rows.append(dict(schema_version=1,forecast_id=r.forecast_id,forecast_file=ref,
                source_forecast_file=ref,market=r.market,system_version='V4-A',model_version=r.model_version,
                ticker=r.ticker,horizon=int(r.horizon_sessions),horizon_sessions=int(r.horizon_sessions),
                information_set=r.information_set,model=r.model,
                data_last_observation_date=r.data_last_observation_date,forecast_for_session_date=r.forecast_for_session_date,
                realized_session_date=r.forecast_for_session_date,predicted_return=r.predicted_return,
                actual=actual,actual_return=actual,error=r.predicted_return-actual,
                direction_correct=int(np.sign(r.predicted_return)==np.sign(actual)),
                interval_covered=int(r.lower_95<=actual<=r.upper_95),
                evaluated_at_utc=now.isoformat(),return_basis='adjusted_close_ratio',
                price_input_sha256=dataset.digest))
    if not rows:return None
    return save(pd.DataFrame(rows),folder,'evaluation',dict(schema_version=1,market=dataset.market,
        rows=len(rows),synthetic=dataset.manifest.get('synthetic',False)))

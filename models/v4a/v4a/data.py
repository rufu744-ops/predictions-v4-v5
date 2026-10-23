"""Validated point-in-time feature and adjusted-price input contract."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd


@dataclass
class Dataset:
    market: str
    sessions: pd.DataFrame
    prices: pd.DataFrame
    features: pd.DataFrame
    columns: list
    digest: str
    manifest: dict


def utc(series,name):
    for value in series:
        if pd.isna(value) or pd.Timestamp(value).tzinfo is None:
            raise ValueError(f'{name} requires explicit timezone timestamps')
    return pd.to_datetime(series,utc=True,errors='raise')


def load(folder,market):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    if manifest.get('schema_version')!=1:
        raise ValueError('Unsupported input schema_version')
    if manifest.get('market')!=market or manifest.get('return_basis')!='adjusted_close_ratio':
        raise ValueError('Input market/return basis mismatch')
    columns=manifest.get('feature_columns',[])
    if not columns or len(set(columns))!=len(columns) or any(not c.startswith('f_') for c in columns):
        raise ValueError('Explicit unique f_ feature columns are required')
    if manifest.get('point_in_time') is not True or not isinstance(manifest.get('source'),str) or not manifest['source'].strip():
        raise ValueError('Input must declare point_in_time=true and its source')
    frames={}
    digests={}
    for name in ['sessions','prices','features']:
        filenames=manifest.get('files',{}).get(name,[name+'.csv'])
        if not isinstance(filenames,list) or not filenames or len(set(filenames))!=len(filenames):
            raise ValueError('Input file list must be unique and nonempty')
        pieces=[]
        for filename in filenames:
            if (not isinstance(filename,str) or Path(filename).name!=filename or
                '/' in filename or '\\' in filename or
                not (filename.endswith('.csv') or filename.endswith('.csv.gz'))):
                raise ValueError('Unsafe input filename')
            path=folder/filename
            if path.is_symlink():raise ValueError('Input symlinks forbidden')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if manifest.get('sha256',{}).get(filename)!=digest:
                raise ValueError(f'Input integrity failure: {filename}')
            digests[filename]=digest
            pieces.append(pd.read_csv(path,dtype={'ticker':str}))
        frames[name]=pd.concat(pieces,ignore_index=True)
    s,p,f=(frames[n] for n in ['sessions','prices','features'])
    for z in [s,p,f]:
        z['date']=pd.to_datetime(z.date,errors='raise').dt.strftime('%Y-%m-%d')
    if s.date.duplicated().any() or not s.date.is_monotonic_increasing:
        raise ValueError('Sessions must be unique and sorted')
    s['close_at_utc']=utc(s.close_at_utc,'close_at_utc')
    if not s.close_at_utc.is_monotonic_increasing or (s.close_at_utc.dt.strftime('%Y-%m-%d')!=s.date).any():
        raise ValueError('Invalid session UTC close ordering/date')
    expected=manifest.get('expected_tickers',[])
    if not expected or len(set(expected))!=len(expected) or any(not isinstance(t,str) or not t.strip() for t in expected):
        raise ValueError('Explicit unique expected_tickers required; no silent small-universe fallback')
    if any(z.ticker.isna().any() or z.ticker.astype(str).str.strip().eq('').any() for z in [p,f]):
        raise ValueError('Null or empty ticker')
    if f.duplicated(['date','ticker']).any() or p.duplicated(['date','ticker']).any():
        raise ValueError('Duplicate feature/price identity')
    if not set(f.date).issubset(set(s.date)) or not set(p.date).issubset(set(s.date)):
        raise ValueError('Input includes non-session dates')
    for c in columns:
        f[c]=pd.to_numeric(f[c],errors='raise')
    if np.isinf(f[columns].to_numpy()).any():
        raise ValueError('Infinite feature')
    p['adjusted_close']=pd.to_numeric(p.adjusted_close,errors='raise')
    if not np.isfinite(p.adjusted_close).all() or (p.adjusted_close<=0).any():
        raise ValueError('Adjusted closes must be positive and finite')
    # No feature-date-only promise: availability is checked against actual exchange close.
    f['available_at_utc']=utc(f.available_at_utc,'available_at_utc')
    closes=s.set_index('date').close_at_utc
    if (f.available_at_utc>f.date.map(closes)).any():
        raise ValueError('Feature available after its session close: rebuild point-in-time input')
    if (f[columns].notna().sum(axis=1)==0).any():
        raise ValueError('All features missing for an input row')
    if not isinstance(manifest.get('synthetic',False),bool):
        raise ValueError('synthetic must be boolean')
    digest=hashlib.sha256(json.dumps(dict(files=digests,manifest=manifest),sort_keys=True).encode()).hexdigest()
    return Dataset(market,s,p.sort_values(['ticker','date']),f.sort_values(['ticker','date']),columns,digest,manifest)


def write_input(folder,market,sessions,prices,features,columns,tickers,source,synthetic=False):
    """Publish V3-exported rows. This function does not manufacture historical availability."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for name,frame in [('sessions',sessions),('prices',prices),('features',features)]:
        frame.to_csv(folder/(name+'.csv'),index=False)
    manifest=dict(schema_version=1,market=market,return_basis='adjusted_close_ratio',point_in_time=True,
        feature_columns=list(columns),expected_tickers=list(tickers),source=source,synthetic=synthetic,
        sha256={n+'.csv':hashlib.sha256((folder/(n+'.csv')).read_bytes()).hexdigest() for n in ['sessions','prices','features']})
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return load(folder,market)

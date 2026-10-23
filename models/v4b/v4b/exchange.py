"""Results-only exchange: no source, input features, coefficients or model state."""
from pathlib import Path,PurePosixPath
import json
import os
import pandas as pd
import numpy as np
from .storage import bundles,digest

PREDICTION_COLUMNS=['schema_version','forecast_id','source_forecast_file','market','system_version',
    'model_version','model','information_set','horizon_sessions','ticker','forecast_created_at_utc',
    'data_last_observation_date','forecast_for_session_date','predicted_return','return_basis','settings_id',
    'return_unit','prediction_std','lower_95','upper_95']
EVALUATION_COLUMNS=['schema_version','forecast_id','forecast_file','market',
    'system_version','model_version','ticker','horizon','horizon_sessions','information_set','model',
    'data_last_observation_date','forecast_for_session_date','realized_session_date','predicted_return',
    'actual','actual_return','error','direction_correct','interval_covered','evaluated_at_utc','return_basis']


def exclusive_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data:
            raise ValueError(f'Existing result changed: {path.name}')
    else:
        with path.open('xb') as f: f.write(data)


def export_results(root,destination):
    root,destination=Path(root),Path(destination)
    if destination.resolve()==root.resolve(): raise ValueError('Use a distinct exchange directory')
    entries=[]
    for family,columns in [('predictions',PREDICTION_COLUMNS),('evaluations',EVALUATION_COLUMNS)]:
        for market in ['JP','US']:
            for path,meta in bundles(root/family/'v4b'/market):
                if meta.get('synthetic',False): continue
                frame=pd.read_csv(path,dtype={'ticker':str})
                if set(columns)-set(frame): raise ValueError('Missing results-only projection columns')
                ref=path.relative_to(root).as_posix();target=destination/ref
                exclusive_bytes(target,frame[columns].to_csv(index=False).encode('utf-8'))
                projected=dict(schema_version=1,csv_file=target.name,csv_sha256=digest(target),market=market,
                    model_version=frame.model_version.iloc[0],rows=len(frame),synthetic=False,projection='results_only_v1')
                if family=='predictions':
                    projected.update(data_last_observation_date=meta['data_last_observation_date'],settings_sha256=meta['settings_sha256'])
                exclusive_bytes(target.with_suffix('.json'),json.dumps(projected,sort_keys=True,indent=2).encode())
                for p in [target,target.with_suffix('.json')]:
                    entries.append(dict(path=p.relative_to(destination).as_posix(),sha256=digest(p)))
    obj=dict(schema_version=1,projection='results_only_v1',files=sorted(entries,key=lambda x:x['path']))
    destination.mkdir(parents=True,exist_ok=True)
    tmp=destination/'index.tmp';tmp.write_text(json.dumps(obj,sort_keys=True,indent=2))
    os.replace(tmp,destination/'index.json')
    return len(entries)//2


def import_results(source,destination):
    source,destination=Path(source),Path(destination)
    index=json.loads((source/'index.json').read_text())
    if index.get('schema_version')!=1 or index.get('projection')!='results_only_v1':
        raise ValueError('Unsupported exchange index')
    entries=index.get('files')
    if not isinstance(entries,list): raise ValueError('Missing exchange files')
    paths={};payloads=[]
    for entry in entries:
        ref=entry['path'];parts=PurePosixPath(ref).parts
        if (len(parts)!=4 or parts[0] not in ['predictions','evaluations'] or parts[1]!='v4b'
            or parts[2] not in ['JP','US'] or PurePosixPath(ref).suffix not in ['.csv','.json']
            or '\\' in ref or '..' in parts or ref in paths):
            raise ValueError('Invalid or duplicate exchange path')
        path=source/ref;target=destination/ref
        if source.resolve() not in path.resolve().parents or destination.resolve() not in target.resolve().parents:
            raise ValueError('Exchange path escaped its root')
        if path.is_symlink() or target.is_symlink(): raise ValueError('Symlink exchange path')
        if digest(path)!=entry['sha256']: raise ValueError(f'Exchange integrity failure: {ref}')
        paths[ref]=entry;payloads.append((target,path.read_bytes()))
    for ref in paths:
        if ref.endswith('.csv'):
            mref=str(PurePosixPath(ref).with_suffix('.json'))
            if mref not in paths: raise ValueError('Missing result manifest')
            meta=json.loads((source/mref).read_text())
            if meta.get('csv_file')!=PurePosixPath(ref).name or meta.get('csv_sha256')!=paths[ref]['sha256'] or meta.get('synthetic') is not False:
                raise ValueError('Result manifest mismatch')
            frame=pd.read_csv(source/ref,dtype={'ticker':str})
            expected=PREDICTION_COLUMNS if ref.startswith('predictions/') else EVALUATION_COLUMNS
            if list(frame.columns)!=expected or not frame.model_version.astype(str).str.startswith('v4b.').all():
                raise ValueError('Unexpected results-only schema')
            if not frame.market.eq(PurePosixPath(ref).parts[2]).all(): raise ValueError('Exchange market mismatch')
            if frame.empty or len(frame)!=meta.get('rows') or not frame.return_basis.eq('adjusted_close_ratio').all():
                raise ValueError('Invalid exchange row count/return basis')
            if not frame.horizon_sessions.isin([1,5,20]).all() or not np.isfinite(frame.predicted_return).all():
                raise ValueError('Invalid exchange horizon/prediction')
            if (pd.to_datetime(frame.forecast_for_session_date)<=pd.to_datetime(frame.data_last_observation_date)).any():
                raise ValueError('Invalid exchange target date')
            if not ref.startswith('predictions/'):
                if not frame.horizon.eq(frame.horizon_sessions).all() or not np.isfinite(frame.actual_return).all():
                    raise ValueError('Invalid exchange evaluation')
        elif str(PurePosixPath(ref).with_suffix('.csv')) not in paths:
            raise ValueError('Orphan result manifest')
    for target,data in payloads:
        if target.exists() and target.read_bytes()!=data: raise ValueError(f'Local history conflict: {target.name}')
    for target,data in payloads: exclusive_bytes(target,data)
    return len(payloads)//2

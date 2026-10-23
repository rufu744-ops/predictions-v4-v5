"""Daily sequential Bayes updates; monthly collapsed posterior quadrature."""
from dataclasses import dataclass,asdict
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from .bayes import Prior,calibrate,assimilate,predictive
from .state import load_checkpoint,save_checkpoint
from . import VERSION


@dataclass(frozen=True)
class Settings:
    horizons: tuple = (1,5,20)
    train_sessions: int = 1260
    min_observations: int = 30
    min_coverage: float = .95
    grid_points: int = 65
    max_grid_points: int = 257
    quadrature_tolerance: float = .002
    prior_width_sd: float = 6.
    log_ratio_mean: float = float(np.log(1e-4))
    log_ratio_sd: float = 2.
    variance_shape: float = 2.5
    variance_scale: float = 1.5e-4
    prior_scale: float = 10.
    information_set: str = 'V3_FEATURES'

    def validate(self):
        if not self.horizons or any(h not in [1,5,20] for h in self.horizons) or len(set(self.horizons))!=len(self.horizons):
            raise ValueError('Horizons must be unique 1/5/20 values')
        if self.train_sessions<60 or self.min_observations<10 or not 0<self.min_coverage<=1 or self.prior_scale<=0:
            raise ValueError('Invalid calibration/coverage settings')
        if self.grid_points<9 or self.grid_points%2!=1 or self.max_grid_points<2*self.grid_points-1 or self.quadrature_tolerance<=0 or self.prior_width_sd<4:
            raise ValueError('Invalid quadrature settings')
        Prior(self.log_ratio_mean,self.log_ratio_sd,self.variance_shape,self.variance_scale,self.prior_scale).validate()


def hash_json(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False).encode()).hexdigest()


def transform(values,median,scale):
    z=np.where(np.isfinite(values),values,median)
    z=np.clip((z-median)/scale,-8,8)
    return np.c_[np.ones(len(z)),z]


def prepare_ticker(dataset,ticker):
    sessions=dataset.sessions.date.tolist()
    price=dataset.prices[dataset.prices.ticker==ticker].set_index('date').adjusted_close.reindex(sessions).to_numpy()
    f=dataset.features[dataset.features.ticker==ticker].set_index('date').reindex(sessions)
    return price,f[dataset.columns].to_numpy(float)


def observations(price,features,cutoff,h):
    # Fixed phase anchored at the FIRST supplied exchange session. Adjacent admitted
    # outcomes have disjoint return intervals, avoiding h-day overlap in the likelihood.
    ends=np.arange(h,cutoff+1,h,dtype=int)
    starts=ends-h
    good=np.isfinite(price[starts]) & np.isfinite(price[ends]) & np.isfinite(features[starts]).any(axis=1)
    ends,starts=ends[good],starts[good]
    return features[starts],price[ends]/price[starts]-1,ends


def history_hash(x,y,steps,through):
    mask=steps<=through
    h=hashlib.sha256()
    for values in [x[mask],y[mask],steps[mask]]:
        # NaN bit patterns are canonicalized before hashing across CSV roundtrips.
        z=np.nan_to_num(values,nan=1.23456789e99).astype('<f8')
        h.update(str(z.shape).encode()); h.update(z.tobytes())
    return h.hexdigest()


def state_path(root,market,ticker,h):
    name=hashlib.sha256(ticker.encode()).hexdigest()[:20]
    return Path(root)/'state/v4b'/market/f'{name}_{h}.json'


def infer_one(dataset,ticker,h,cutoff,settings,root,settings_id):
    price,features=prepare_ticker(dataset,ticker)
    if not np.isfinite(price[cutoff]) or not np.isfinite(features[cutoff]).any():
        raise ValueError('No current quote/features')
    x,y,steps=observations(price,features,cutoff,h)
    minimum=max(settings.min_observations,len(dataset.columns)+5)
    path=state_path(root,dataset.market,ticker,h)
    cached=load_checkpoint(path)
    month=dataset.sessions.date.iloc[cutoff][:7]
    reason='initial'
    reuse=False
    if cached and cached.get('settings_id')==settings_id and cached.get('calendar_start')==dataset.sessions.date.iloc[0]:
        end=cached['state_step']
        if end>cutoff:
            reason='historical_origin'
        elif cached['history_sha256']!=history_hash(x,y,steps,end):
            reason='historical_input_revision'
        elif cached['calibration_month']!=month:
            reason='monthly'
        else:
            reuse=True;reason='incremental'
    elif cached:
        reason='configuration_changed'
    prior=Prior(settings.log_ratio_mean,settings.log_ratio_sd,settings.variance_shape,settings.variance_scale,settings.prior_scale)
    if reuse:
        median=np.asarray(cached['median']);scale=np.asarray(cached['scale'])
        bank=cached['bank'];new=steps>int(bank['state_step'])
        bank=assimilate(bank,transform(x[new],median,scale),y[new],steps[new])
        calibration_step=cached['calibration_step'];calibration_month=cached['calibration_month']
        if bank['boundary_mass']>=.001 or bank['diagnostics']['max_grid_weight']>=.35:
            reuse=False;reason='quadrature_resolution_refresh'
    if not reuse:
        select=steps>=max(0,cutoff-settings.train_sessions+1)
        tx,ty,ts=x[select],y[select],steps[select]
        if len(ty)<minimum:
            raise ValueError(f'Insufficient non-overlapping matured outcomes: {len(ty)} < {minimum} (h={h})')
        median=np.array([np.nanmedian(v) if np.isfinite(v).any() else 0. for v in tx.T])
        filled=np.where(np.isfinite(tx),tx,median)
        scale=filled.std(axis=0);scale=np.where(scale>1e-8,scale,1.)
        bank=calibrate(transform(tx,median,scale),ty,ts,prior,h,
            settings.grid_points,settings.max_grid_points,settings.quadrature_tolerance,settings.prior_width_sd,
            check_x=transform(features[cutoff:cutoff+1],median,scale)[0],check_target_step=cutoff+h)
        calibration_step=int(cutoff);calibration_month=month
    xt=transform(features[cutoff:cutoff+1],median,scale)[0]
    result=predictive(bank,xt,cutoff+h)
    if not np.isfinite(list(result.values())).all():raise FloatingPointError('Invalid posterior predictive distribution')
    saved=dict(ticker=ticker,horizon=h,settings_id=settings_id,model_version=VERSION,
        feature_columns=dataset.columns,calendar_start=dataset.sessions.date.iloc[0],
        calibration_month=calibration_month,calibration_step=calibration_step,
        median=median.tolist(),scale=scale.tolist(),state_step=int(bank['state_step']),bank=bank,
        history_sha256=history_hash(x,y,steps,int(bank['state_step'])),update_reason=reason)
    r_mean=bank['scales']/(bank['shapes']-1.)
    output=dict(ticker=ticker,horizon_sessions=h,model='Bayesian_TVP_Kalman',**result,
        close_at_forecast=float(price[cutoff]),state_last_observation_date=dataset.sessions.date.iloc[int(bank['state_step'])],
        parameter_estimated_through=dataset.sessions.date.iloc[calibration_step],
        posterior_updated_through=dataset.sessions.date.iloc[int(bank['state_step'])],
        posterior_q_mean=float(bank['weights']@(np.exp(bank['log_ratios'])*r_mean)),
        posterior_r_mean=float(bank['weights']@r_mean),
        grid_points=int(bank['points']),calibration_quadrature_error=bank['diagnostics']['refinement_error'],
        boundary_mass=bank['boundary_mass'],max_grid_weight=bank['diagnostics']['max_grid_weight'],update_reason=reason)
    return output,(path,saved)


def run(dataset,root,settings=Settings(),as_of=None,now=None):
    from .storage import bundles,save_prediction
    settings.validate()
    now=pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    if now.tzinfo is None:
        raise ValueError('now must carry timezone')
    s=dataset.sessions
    completed=s[s.close_at_utc<=now]
    if as_of:
        completed=completed[completed.date<=str(as_of)]
    if completed.empty:
        raise ValueError('No completed exchange sessions')
    cutoff=int(completed.index[-1])
    if cutoff+max(settings.horizons)>=len(s):
        raise ValueError('Calendar must extend at least 20 exchange sessions beyond the forecast origin')
    origin=s.date.iloc[cutoff]
    target={h:s.date.iloc[cutoff+h] for h in settings.horizons}
    identity=dict(model_version=VERSION,settings=asdict(settings),feature_columns=dataset.columns,
        source=dataset.manifest['source'],calendar_start=s.date.iloc[0])
    settings_id=hash_json(identity)
    folder=Path(root)/'predictions/v4b'/dataset.market
    for path,meta in bundles(folder):
        if meta.get('data_last_observation_date')==origin and meta.get('settings_sha256')==settings_id:
            return dict(status='already_forecast',forecast_file=str(path),rows=meta['rows'])
    rows=[];states=[];failures=[]
    expected=dataset.manifest['expected_tickers']
    for ticker in expected:
        ticker_rows=[];ticker_states=[]
        try:
            for h in settings.horizons:
                row,state=infer_one(dataset,ticker,h,cutoff,settings,root,settings_id)
                row['forecast_for_session_date']=target[h]
                ticker_rows.append(row);ticker_states.append(state)
        except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError) as exc:
            failures.append(dict(ticker=ticker,reason=str(exc)))
            continue
        rows.extend(ticker_rows);states.extend(ticker_states)
    coverage=len(rows)/len(settings.horizons)/len(expected)
    diagnostics=dict(market=dataset.market,origin=origin,coverage=coverage,expected_tickers=len(expected),
        failures=failures,input_sha256=dataset.digest,settings_id=settings_id,synthetic=dataset.manifest.get('synthetic',False))
    status_dir=Path(root)/'output/status/v4b';status_dir.mkdir(parents=True,exist_ok=True)
    (status_dir/f'{dataset.market}.json').write_text(json.dumps(diagnostics,indent=2))
    if coverage+1e-12<settings.min_coverage:
        raise RuntimeError(f'Forecast coverage {coverage:.1%} < {settings.min_coverage:.1%}; see output/status/v4b/{dataset.market}.json; no forecast saved')
    z=pd.DataFrame(rows)
    z['schema_version']=1;z['market']=dataset.market;z['system_version']='V4-B';z['model_version']=VERSION
    z['information_set']=settings.information_set;z['settings_id']=settings_id
    z['data_last_observation_date']=origin;z['forecast_created_at_utc']=now.isoformat()
    z['return_basis']='adjusted_close_ratio';z['return_unit']='fraction'
    meta=dict(diagnostics,settings=asdict(settings),settings_sha256=settings_id,feature_columns=dataset.columns,
        data_last_observation_date=origin,forecast_cutoff_at_utc=s.close_at_utc.iloc[cutoff].isoformat(),
        model_version=VERSION,rows=len(z),input_source=dataset.manifest['source'],
        estimation='Bayesian collapsed quadrature over log(Q/R); inverse-gamma R; random-walk coefficients',
        horizon_likelihood='fixed-phase non-overlapping cumulative outcomes',
        uncertainty='posterior predictive Student-t mixture: state, observation, Q/R parameter uncertainty; conditional on model and fixed prior hyperparameters')
    path=save_prediction(z,folder,meta)
    # State never crosses account boundaries and is committed only after a valid forecast.
    for state in states:
        save_checkpoint(*state)
    return dict(status='forecast_saved',forecast_file=str(path),rows=len(z),coverage=coverage)

"""Random-walk regression; exact scalar-observation Kalman likelihood.

P0 = prior_scale * R * I, Q = lambda * R * I.
A scalar lambda is maximum-likelihood estimated, R is profiled analytically.
No smoothing, future outcomes, or estimated Bayesian hyperparameters are used.
"""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize_scalar


@dataclass
class State:
    mean: np.ndarray
    covariance: np.ndarray
    step: int


def update(state, x, y, step, q, r):
    if step <= state.step:
        raise ValueError('Kalman updates must advance time; outcome already assimilated')
    x=np.asarray(x,dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y) or q<0 or r<=0:
        raise ValueError('Invalid Kalman observation/noise')
    prior=state.covariance+np.eye(len(x))*q*(step-state.step)
    px=prior@x
    variance=float(x@px+r)
    error=float(y-x@state.mean)
    if not np.isfinite(variance) or variance<=0:
        raise FloatingPointError('Nonpositive innovation variance')
    gain=px/variance
    mean=state.mean+gain*error
    # Scalar rank-one update, then enforce symmetry against floating-point drift.
    covariance=prior-np.outer(px,px)/variance
    covariance=(covariance+covariance.T)*.5
    return State(mean,covariance,int(step)),error,variance


def filter_data(x,y,steps,q,r,prior_scale=10.):
    x=np.asarray(x,float);y=np.asarray(y,float);steps=np.asarray(steps,int)
    if x.ndim!=2 or len(x)!=len(y) or len(y)!=len(steps) or not len(y):
        raise ValueError('Filter shape mismatch or empty observations')
    if np.any(np.diff(steps)<=0):
        raise ValueError('Duplicate or unordered observation times')
    state=State(np.zeros(x.shape[1]),np.eye(x.shape[1])*prior_scale*r,int(steps[0])-1)
    errors=[]; variances=[]
    for row,value,step in zip(x,y,steps):
        state,error,variance=update(state,row,value,int(step),q,r)
        errors.append(error);variances.append(variance)
    return state,np.asarray(errors),np.asarray(variances)


def fit_noise(x,y,steps,maxiter=32,prior_scale=10.):
    """Gaussian marginal ML, conditional on supplied predictors and zero initial mean."""
    n=len(y)
    if n<10 or not np.isfinite(y).all():
        raise ValueError('Need at least 10 finite matured outcomes for ML')
    def objective(log_ratio):
        ratio=float(np.exp(log_ratio))
        _,errors,scale_variances=filter_data(x,y,steps,ratio,1.,prior_scale)
        r=max(float(np.mean(errors**2/scale_variances)),1e-10)
        nll=.5*(n*np.log(2*np.pi*r)+np.log(scale_variances).sum()+np.sum(errors**2/scale_variances)/r)
        return float(nll)
    bounds=(np.log(1e-9),np.log(.1))
    opt=minimize_scalar(objective,bounds=bounds,method='bounded',options={'maxiter':maxiter,'xatol':.025})
    if not opt.success or not np.isfinite(opt.fun):
        raise RuntimeError('Noise maximum likelihood did not converge')
    ratio=float(np.exp(opt.x))
    _,errors,scales=filter_data(x,y,steps,ratio,1.,prior_scale)
    r=max(float(np.mean(errors**2/scales)),1e-10)
    q=ratio*r
    state,_,_=filter_data(x,y,steps,q,r,prior_scale)
    return state,dict(q=q,r=r,q_over_r=ratio,nll=float(opt.fun),n_obs=n,
        optimizer_success=True,near_bound=bool(min(opt.x-bounds[0],bounds[1]-opt.x)<.1))


def forecast(state,x,target_step,q,r):
    if target_step<state.step:
        raise ValueError('Forecast cannot precede filtered state')
    x=np.asarray(x,float)
    covariance=state.covariance+np.eye(len(x))*q*(target_step-state.step)
    return float(x@state.mean),float(x@covariance@x+r)

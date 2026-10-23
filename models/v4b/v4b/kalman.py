"""Conditional Kalman calculations with Q/R=ratio and normalized R=1.
Used by the collapsed Bayesian integrator; no maximum-likelihood estimation here."""
from dataclasses import dataclass
import numpy as np


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


def forecast(state,x,target_step,q,r):
    if target_step<state.step:
        raise ValueError('Forecast cannot precede filtered state')
    x=np.asarray(x,float)
    covariance=state.covariance+np.eye(len(x))*q*(target_step-state.step)
    return float(x@state.mean),float(x@covariance@x+r)

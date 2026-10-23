"""Collapsed Bayesian TVP regression: quadrature over log(Q/R), conjugate R.

The state model is exactly linear Gaussian conditional on (lambda, R).
Q=lambda*R*I; beta0|R ~ N(0, prior_scale*R*I).
log(lambda) ~ Normal(log_ratio_mean, log_ratio_sd^2), R ~ InvGamma(a0,b0).
No MCMC or latent state path sampling. Grid approximation is checked by refinement.
"""
from dataclasses import dataclass
import numpy as np
from scipy.special import gammaln,logsumexp
from scipy.stats import norm,t
from scipy.optimize import brentq
from .kalman import State,filter_data,update


@dataclass(frozen=True)
class Prior:
    log_ratio_mean: float = float(np.log(1e-4))
    log_ratio_sd: float = 2.
    shape: float = 2.5
    scale_per_session: float = 1.5e-4
    state_scale: float = 10.

    def validate(self):
        if not np.isfinite([self.log_ratio_mean,self.log_ratio_sd,self.shape,self.scale_per_session,self.state_scale]).all():
            raise ValueError('Nonfinite prior hyperparameter')
        if self.log_ratio_sd<=0 or self.shape<=1 or self.scale_per_session<=0 or self.state_scale<=0:
            raise ValueError('Priors require positive scales and shape>1 for finite predictive variance')


def conditional(x,y,steps,ratio,prior,horizon):
    state,errors,variances=filter_data(x,y,steps,float(ratio),1.,prior.state_scale)
    a=prior.shape+.5*len(y);b0=prior.scale_per_session*horizon
    b=b0+.5*np.sum(errors**2/variances)
    evidence=(gammaln(a)-gammaln(prior.shape)+prior.shape*np.log(b0)-a*np.log(b)
              -.5*np.log(variances).sum()-.5*len(y)*np.log(2*np.pi))
    return state,float(a),float(b),float(evidence)


def grid_posterior(x,y,steps,prior,horizon,points=65,width_sd=6.):
    prior.validate()
    if points<9 or points%2!=1:raise ValueError('Grid size must be odd and >=9')
    if len(y)<10 or np.asarray(x).ndim!=2 or len(x)!=len(y):raise ValueError('Insufficient/shaped calibration observations')
    nodes=np.linspace(prior.log_ratio_mean-width_sd*prior.log_ratio_sd,
                      prior.log_ratio_mean+width_sd*prior.log_ratio_sd,points)
    means=[];covariances=[];shapes=[];scales=[];logs=[]
    for node in nodes:
        state,a,b,evidence=conditional(x,y,steps,np.exp(node),prior,horizon)
        means.append(state.mean);covariances.append(state.covariance);shapes.append(a);scales.append(b)
        logs.append(evidence+norm.logpdf(node,prior.log_ratio_mean,prior.log_ratio_sd))
    spacing=nodes[1]-nodes[0]
    quadrature=np.full(points,spacing);quadrature[[0,-1]]*=.5
    raw=np.asarray(logs)+np.log(quadrature);log_z=float(logsumexp(raw))
    weights=np.exp(raw-log_z)
    return dict(log_ratios=nodes,weights=weights,log_weights=raw-log_z,means=np.asarray(means),covariances=np.asarray(covariances),
        shapes=np.asarray(shapes),scales=np.asarray(scales),state_step=int(steps[-1]),
        log_evidence=log_z,boundary_mass=float(weights[:2].sum()+weights[-2:].sum()),points=points)


def moment_summary(bank,x,target_step):
    x=np.asarray(x,float);w=bank['weights'];gap=target_step-int(bank['state_step'])
    if gap<0:raise ValueError('Forecast before filtered state')
    locations=bank['means']@x
    f=(np.einsum('i,kij,j->k',x,bank['covariances'],x)+gap*np.exp(bank['log_ratios'])*float(x@x)+1.)
    if (f<=0).any() or not np.isfinite(f).all():raise FloatingPointError('Invalid conditional forecast variance')
    scales_squared=bank['scales']/bank['shapes']*f
    variances=bank['scales']/(bank['shapes']-1.)*f
    mean=float(w@locations)
    within=float(w@variances);between=float(w@((locations-mean)**2))
    return dict(mean=mean,variance=within+between,within_variance=within,between_variance=between,
        locations=locations,scales=np.sqrt(scales_squared),dfs=2*bank['shapes'])


def predictive(bank,x,target_step):
    z=moment_summary(bank,x,target_step);w=bank['weights'];loc=z['locations'];scale=z['scales'];df=z['dfs']
    def cdf(value):return float(w@t.cdf((value-loc)/scale,df))
    def quantile(prob):
        lo=float(np.min(loc+scale*t.ppf(prob/10,df)))
        hi=float(np.max(loc+scale*t.ppf(1-(1-prob)/10,df)))
        for _ in range(15):
            if cdf(lo)<=prob<=cdf(hi):break
            width=max(hi-lo,1e-6);lo-=width;hi+=width
        return float(brentq(lambda value:cdf(value)-prob,lo,hi,xtol=1e-11))
    return dict(predicted_return=z['mean'],prediction_std=float(np.sqrt(z['variance'])),
        lower_95=quantile(.025),upper_95=quantile(.975),probability_positive=1-cdf(0.),
        posterior_between_variance=z['between_variance'],posterior_within_variance=z['within_variance'])


def calibrate(x,y,steps,prior,horizon,grid_points=65,max_points=257,tolerance=.002,width_sd=6.,check_x=None,check_target_step=None):
    previous=grid_posterior(x,y,steps,prior,horizon,grid_points,width_sd)
    # Compare quadrature normalization (marginal likelihood) AND posterior log-ratio mean.
    points=grid_points;converged=False;error=np.inf
    while 2*points-1<=max_points:
        points=2*points-1
        current=grid_posterior(x,y,steps,prior,horizon,points,width_sd)
        z_error=abs(current['log_evidence']-previous['log_evidence'])
        m_error=abs(float(current['weights']@current['log_ratios']-previous['weights']@previous['log_ratios']))
        error=max(z_error,m_error)
        if check_x is not None:
            if check_target_step is None:raise ValueError('Forecast precision check requires target step')
            before=predictive(previous,check_x,check_target_step);after=predictive(current,check_x,check_target_step)
            unit=max(before['prediction_std'],after['prediction_std'],1e-12)
            error=max(error,*[abs(after[name]-before[name])/unit for name in
                ['predicted_return','prediction_std','lower_95','upper_95']])
        if error<=tolerance and current['boundary_mass']<.001 and float(current['weights'].max())<.35:
            converged=True;break
        previous=current
    if not converged:
        raise RuntimeError(f'Bayesian quadrature not resolved: grid={points}, error={error:.4g}; increase max-grid-points or check prior range')
    current['diagnostics']=dict(method='collapsed_1D_quadrature',grid_points=points,refinement_error=float(error),
        boundary_mass=current['boundary_mass'],quadrature_converged=True,
        effective_grid_nodes=float(1/np.sum(current['weights']**2)),max_grid_weight=float(current['weights'].max()))
    return current


def assimilate(bank,x,y,steps):
    """Exact sequential Bayes update on the saved quadrature grid; no repeated outcomes."""
    result={k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in bank.items()}
    for row,value,step in zip(x,y,steps):
        if int(step)<=int(result['state_step']):raise ValueError('Duplicate/out-of-order Bayesian update')
        logs=result['log_weights'].copy()
        for k,ratio in enumerate(np.exp(result['log_ratios'])):
            state=State(result['means'][k],result['covariances'][k],int(result['state_step']))
            updated,error,variance=update(state,row,value,int(step),ratio,1.)
            a,b=result['shapes'][k],result['scales'][k]
            logs[k]+=t.logpdf(error/np.sqrt(b/a*variance),2*a)-.5*np.log(b/a*variance)
            result['means'][k]=updated.mean;result['covariances'][k]=updated.covariance
            result['shapes'][k]=a+.5;result['scales'][k]=b+.5*error**2/variance
        normalizer=float(logsumexp(logs))
        result['log_weights']=logs-normalizer;result['weights']=np.exp(result['log_weights'])
        result['log_evidence']+=normalizer;result['state_step']=int(step)
    result['boundary_mass']=float(result['weights'][:2].sum()+result['weights'][-2:].sum())
    result['diagnostics']=dict(result['diagnostics'],boundary_mass=result['boundary_mass'],
        effective_grid_nodes=float(1/np.sum(result['weights']**2)),max_grid_weight=float(result['weights'].max()))
    return result

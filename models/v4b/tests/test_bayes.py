import unittest
import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_t,t
from scipy.integrate import quad
from v4b.bayes import Prior,conditional,grid_posterior,calibrate,assimilate,predictive,moment_summary


class BayesianTests(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(42)
        self.x=np.c_[np.ones(24),self.rng.normal(size=24)]
        self.y=.003*self.x[:,1]+self.rng.normal(0,.01,24)
        self.steps=np.arange(1,25,dtype=int)*2
        self.prior=Prior()

    def test_collapsed_evidence_against_dense_multivariate_student_t(self):
        ratio=.0003;prior=self.prior
        state,a,b,evidence=conditional(self.x,self.y,self.steps,ratio,prior,5)
        dt=self.steps-(self.steps[0]-1)
        h=(self.x@self.x.T)*(prior.state_scale+ratio*np.minimum.outer(dt,dt))+np.eye(len(self.y))
        b0=prior.scale_per_session*5
        dense=multivariate_t.logpdf(self.y,loc=np.zeros(len(self.y)),shape=b0/prior.shape*h,df=2*prior.shape)
        self.assertAlmostEqual(evidence,dense,places=9)
        self.assertAlmostEqual(b,b0+.5*self.y@np.linalg.solve(h,self.y),places=12)
        self.assertAlmostEqual(a,prior.shape+len(self.y)/2)

    def test_grid_against_independent_adaptive_quadrature(self):
        prior=self.prior;bank=calibrate(self.x,self.y,self.steps,prior,1,33,257,.0002)
        from scipy.stats import norm
        def log_density(node):
            return conditional(self.x,self.y,self.steps,np.exp(node),prior,1)[-1]+norm.logpdf(node,prior.log_ratio_mean,prior.log_ratio_sd)
        center=bank['log_evidence']
        lo=prior.log_ratio_mean-6*prior.log_ratio_sd;hi=prior.log_ratio_mean+6*prior.log_ratio_sd
        mass=quad(lambda z:np.exp(log_density(z)-center),lo,hi,epsabs=1e-9)[0]
        mean=quad(lambda z:z*np.exp(log_density(z)-center),lo,hi,epsabs=1e-9)[0]/mass
        self.assertAlmostEqual(mass,1.,places=5)
        self.assertAlmostEqual(float(bank['weights']@bank['log_ratios']),mean,places=5)

    def test_sequential_bayes_equals_batch_on_same_grid(self):
        prefix=grid_posterior(self.x[:16],self.y[:16],self.steps[:16],self.prior,1,65)
        prefix['diagnostics']={}
        streamed=assimilate(prefix,self.x[16:],self.y[16:],self.steps[16:])
        batch=grid_posterior(self.x,self.y,self.steps,self.prior,1,65)
        for name in ['weights','log_weights','means','covariances','shapes','scales']:
            np.testing.assert_allclose(streamed[name],batch[name],atol=2e-11,rtol=2e-11)
        self.assertAlmostEqual(streamed['log_evidence'],batch['log_evidence'],places=9)
        with self.assertRaises(ValueError):assimilate(streamed,self.x[-1:],self.y[-1:],self.steps[-1:])

    def test_mixture_quantiles_and_total_variance(self):
        bank=calibrate(self.x,self.y,self.steps,self.prior,1,33,257,.002)
        xt=np.array([1.,.7]);future=51
        result=predictive(bank,xt,future);mom=moment_summary(bank,xt,future)
        for name,prob in [('lower_95',.025),('upper_95',.975)]:
            cdf=bank['weights']@t.cdf((result[name]-mom['locations'])/mom['scales'],mom['dfs'])
            self.assertAlmostEqual(float(cdf),prob,places=8)
        self.assertAlmostEqual(result['prediction_std']**2,mom['within_variance']+mom['between_variance'])
        self.assertGreaterEqual(mom['between_variance'],0)
        self.assertTrue(0<=result['probability_positive']<=1)

    def test_conjugate_variance_and_unchanged_unidentified_ratio_prior(self):
        x=np.zeros((20,1));y=np.linspace(-.02,.02,20);steps=np.arange(1,21)
        prior=Prior(log_ratio_sd=.5)
        bank=calibrate(x,y,steps,prior,1,33,129,.0002)
        np.testing.assert_allclose(bank['shapes'],prior.shape+10)
        np.testing.assert_allclose(bank['scales'],prior.scale_per_session+.5*(y@y))
        # x=0 contains no information about lambda: posterior must equal its prior.
        mean_lambda=float(bank['weights']@np.exp(bank['log_ratios']))
        self.assertAlmostEqual(mean_lambda,np.exp(prior.log_ratio_mean+.5*prior.log_ratio_sd**2),places=10)
        result=predictive(bank,[1.],25)
        rmean=(prior.scale_per_session+.5*(y@y))/(prior.shape+10-1)
        expected=rmean*(prior.state_scale+25*mean_lambda+1)
        self.assertAlmostEqual(result['prediction_std']**2,expected,places=10)

    def test_unresolved_quadrature_is_not_called_converged(self):
        with self.assertRaises(RuntimeError):
            calibrate(self.x,self.y,self.steps,self.prior,1,9,17,1e-14)


if __name__=='__main__':unittest.main()

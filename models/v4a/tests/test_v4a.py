import copy
from pathlib import Path
import json
import tempfile
import unittest
import numpy as np
import pandas as pd
from scipy.linalg import cho_factor,cho_solve
from demo import make_input
from v4a.data import load,write_input
from v4a.engine import Settings,run,observations,prepare_ticker
from v4a.kalman import State,update,filter_data,fit_noise,forecast
from v4a.storage import bundles,evaluate
from v4a.exchange import export_results,import_results


class KalmanTests(unittest.TestCase):
    def test_scalar_known_update_and_forecast(self):
        initial=State(np.array([0.]),np.array([[1.]]),0)
        state,error,variance=update(initial,[1.],2.,1,.1,.5)
        self.assertAlmostEqual(variance,1.6)
        self.assertAlmostEqual(state.mean[0],2*1.1/1.6)
        self.assertAlmostEqual(state.covariance[0,0],1.1*.5/1.6)
        mean,var=forecast(state,[1.],3,.1,.5)
        self.assertAlmostEqual(var,state.covariance[0,0]+.2+.5)
        with self.assertRaises(ValueError):update(state,[1.],2.,1,.1,.5)

    def test_dense_gaussian_likelihood_and_posterior(self):
        rng=np.random.default_rng(4);x=np.c_[np.ones(15),rng.normal(size=15)]
        y=rng.normal(0,.01,15);steps=np.arange(1,16)*3;q,r,prior=2e-5,1e-4,10.
        state,e,f=filter_data(x,y,steps,q,r,prior);start=steps[0]-1
        cov=(x@x.T)*(prior*r+q*np.minimum.outer(steps-start,steps-start))+r*np.eye(len(y))
        factor=cho_factor(cov)
        dense=.5*(len(y)*np.log(2*np.pi)+2*np.log(np.diag(factor[0])).sum()+y@cho_solve(factor,y))
        filtered=.5*(len(y)*np.log(2*np.pi)+np.log(f).sum()+np.sum(e**2/f))
        self.assertAlmostEqual(dense,filtered,places=9)
        cross=(prior*r+q*(steps-start))[:,None]*x
        np.testing.assert_allclose(state.mean,cross.T@cho_solve(factor,y),rtol=1e-10,atol=1e-12)
        self.assertGreater(np.linalg.eigvalsh(state.covariance).min(),-1e-12)

    def test_noise_mle_likelihood(self):
        rng=np.random.default_rng(9);x=np.c_[np.ones(100),rng.normal(size=100)]
        y=.005*x[:,1]+rng.normal(0,.01,100)
        state,p=fit_noise(x,y,np.arange(1,101),maxiter=24)
        self.assertTrue(p['optimizer_success']);self.assertGreater(p['q'],0);self.assertGreater(p['r'],0)
        _,e,f=filter_data(x,y,np.arange(1,101),p['q'],p['r'])
        self.assertAlmostEqual(.5*(100*np.log(2*np.pi)+np.log(f).sum()+np.sum(e**2/f)),p['nll'],places=7)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=make_input(self.root/'inputs','US',n_tickers=2)
        self.settings=Settings(maxiter=24);self.idx=790
        self.now=pd.Timestamp(self.data.sessions.close_at_utc.iloc[self.idx])
    def tearDown(self):self.temp.cleanup()
    def execute(self,idx=None,root=None,data=None):
        idx=self.idx if idx is None else idx;d=data or self.data
        return run(d,root or self.root,self.settings,as_of=d.sessions.date.iloc[idx],now=pd.Timestamp(d.sessions.close_at_utc.iloc[idx]))

    def test_horizons_matured_nonoverlap(self):
        price,features=prepare_ticker(self.data,'DEMO000')
        for h in [1,5,20]:
            x,y,steps=observations(price,features,self.idx,h)
            self.assertLessEqual(steps.max(),self.idx);self.assertTrue((np.diff(steps)>=h).all())
            np.testing.assert_allclose(y,price[steps]/price[steps-h]-1)

    def test_repeat_incremental_monthly(self):
        result=self.execute();self.assertEqual(result['rows'],6)
        path=Path(result['forecast_file']);original=path.read_bytes()
        self.assertEqual(self.execute()['status'],'already_forecast');self.assertEqual(path.read_bytes(),original)
        z=pd.read_csv(self.execute(self.idx+1)['forecast_file'])
        self.assertTrue(z.update_reason.eq('incremental').all())
        self.assertTrue((z.state_last_observation_date<=z.data_last_observation_date).all())
        future=next(i for i in range(self.idx+1,839) if self.data.sessions.date.iloc[i][:7]!=self.data.sessions.date.iloc[self.idx][:7])
        z=pd.read_csv(self.execute(future)['forecast_file']);self.assertTrue(z.update_reason.eq('monthly').all())

    def test_future_changes_cannot_change_past_predictions(self):
        first=pd.read_csv(self.execute(root=self.root/'a')['forecast_file'])
        altered=copy.deepcopy(self.data)
        altered.prices.loc[altered.prices.date>altered.sessions.date.iloc[self.idx],'adjusted_close']*=2
        for c in altered.columns:altered.features.loc[altered.features.date>altered.sessions.date.iloc[self.idx],c]+=100
        second=pd.read_csv(self.execute(root=self.root/'b',data=altered)['forecast_file'])
        np.testing.assert_allclose(first.predicted_return,second.predicted_return,rtol=0,atol=0)
        np.testing.assert_allclose(first.prediction_std,second.prediction_std,rtol=0,atol=0)

    def test_revision_rebuilds_state_without_changing_saved_forecast(self):
        first=self.execute();path=Path(first['forecast_file']);old=path.read_bytes()
        revised=copy.deepcopy(self.data)
        day=revised.sessions.date.iloc[780]
        revised.prices.loc[revised.prices.date==day,'adjusted_close']*=1.01
        result=self.execute(self.idx+1,data=revised)
        rows=pd.read_csv(result['forecast_file'])
        self.assertTrue(rows.update_reason.eq('historical_input_revision').all())
        self.assertEqual(path.read_bytes(),old)

    def test_missing_quote_no_shift_and_coverage_stop(self):
        altered=copy.deepcopy(self.data);day=altered.sessions.date.iloc[self.idx]
        altered.prices=altered.prices[~((altered.prices.ticker=='DEMO000')&(altered.prices.date==day))]
        with self.assertRaisesRegex(RuntimeError,'coverage'):self.execute(data=altered)
        self.assertFalse(list((self.root/'predictions').rglob('*.csv')))

    def test_input_availability_and_integrity(self):
        d=self.data;bad=d.features.copy();bad.loc[0,'available_at_utc']='2099-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'after'):
            write_input(self.root/'bad','US',d.sessions,d.prices,bad,d.columns,d.manifest['expected_tickers'],'TEST',True)
        with (self.root/'inputs/prices.csv').open('a') as f:f.write('\n')
        with self.assertRaisesRegex(ValueError,'integrity'):load(self.root/'inputs','US')

    def test_exact_session_evaluation_idempotent(self):
        self.execute();self.assertIsNone(evaluate(self.data,self.root,self.now))
        h1=self.idx+1;stamp=pd.Timestamp(self.data.sessions.close_at_utc.iloc[h1])
        self.assertIsNone(evaluate(self.data,self.root,stamp-pd.Timedelta(seconds=1)))
        self.assertEqual(len(pd.read_csv(evaluate(self.data,self.root,stamp))),2)
        stamp=pd.Timestamp(self.data.sessions.close_at_utc.iloc[835])
        self.assertEqual(len(pd.read_csv(evaluate(self.data,self.root,stamp))),4)
        self.assertIsNone(evaluate(self.data,self.root,stamp))
        all_e=pd.concat([pd.read_csv(p) for p,_ in bundles(self.root/'evaluations/v4a/US')])
        self.assertEqual(all_e.forecast_id.nunique(),6)
        p=self.data.prices.set_index(['ticker','date']).adjusted_close
        for r in all_e.itertuples():self.assertAlmostEqual(r.actual_return,p[r.ticker,r.forecast_for_session_date]/p[r.ticker,r.data_last_observation_date]-1)

    def test_result_projection_import_change_detection(self):
        # Synthetic fixture temporarily exercises real-export branch only in this temp dir.
        d=copy.deepcopy(self.data);d.manifest['synthetic']=False
        self.execute(data=d);evaluate(d,self.root,pd.Timestamp(d.sessions.close_at_utc.iloc[835]))
        exchange=self.root/'exchange';dashboard=self.root/'dashboard-copy'
        self.assertEqual(export_results(self.root,exchange),2)
        self.assertEqual(import_results(exchange,dashboard),2);self.assertEqual(import_results(exchange,dashboard),2)
        for path in (exchange/'predictions').rglob('*.csv'):
            frame=pd.read_csv(path);self.assertNotIn('q',frame);self.assertNotIn('r',frame);self.assertNotIn('state_mean',frame)
        for path in (exchange/'evaluations').rglob('*.csv'):
            self.assertNotIn('source_forecast_file',pd.read_csv(path))  # legacy normalize renames forecast_file
        p=next((exchange/'predictions').rglob('*.csv'))
        with p.open('a') as f:f.write('changed')
        with self.assertRaisesRegex(ValueError,'integrity'):import_results(exchange,dashboard)

    def test_synthetic_not_exported(self):
        self.execute();self.assertEqual(export_results(self.root,self.root/'exchange'),0)
        self.assertEqual(json.loads((self.root/'exchange/index.json').read_text())['files'],[])


if __name__=='__main__':unittest.main()

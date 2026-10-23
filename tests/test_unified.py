import importlib.util
from pathlib import Path
import sys,tempfile,subprocess
import unittest
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'models/v4a'));sys.path.insert(0,str(ROOT/'models/v4b'))
from v4a.engine import run as run_a,Settings as ASettings
from v4b.engine import run as run_b,Settings as BSettings
from v4a.storage import evaluate as evaluate_a
from v4b.storage import evaluate as evaluate_b
from common.exchange import export_results,import_results
from tools.merge_runs import merge
spec=importlib.util.spec_from_file_location('synthetic_fixture',ROOT/'models/v4a/demo.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class UnifiedTests(unittest.TestCase):
    def test_a_b_matrix_merge_single_results_feed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=fixture.make_input(root/'inputs','US',1)
            data.manifest['synthetic']=False  # confined synthetic fixture for export-branch testing
            as_of=data.sessions.date.iloc[790];now=pd.Timestamp(data.sessions.close_at_utc.iloc[790]);mature=pd.Timestamp(data.sessions.close_at_utc.iloc[835])
            jobs=root/'jobs';jobs.mkdir()
            for model,runner,settings,evaluator in [
                ('a',run_a,ASettings(maxiter=24),evaluate_a),
                ('b',run_b,BSettings(grid_points=17,max_grid_points=129,quadrature_tolerance=.02),evaluate_b)]:
                job=root/model
                runner(data,job,settings,as_of=as_of,now=now);evaluator(data,job,now=mature)
                subprocess.run([sys.executable,str(ROOT/'tools/stage_logs.py'),'--root',str(job),'--model',model,'--market','US','--destination',str(jobs/model)],check=True)
            combined=root/'combined';self.assertGreater(merge(jobs,combined),0)
            first={p.relative_to(combined).as_posix():p.read_bytes() for p in combined.rglob('*.csv')}
            merge(jobs,combined)
            for ref,value in first.items():self.assertEqual((combined/ref).read_bytes(),value)
            self.assertEqual(export_results(combined,root/'results'),4)
            self.assertEqual(import_results(root/'results',root/'dashboard'),4)
            frames=[pd.read_csv(p) for p in (root/'dashboard/predictions').rglob('*.csv')]
            self.assertEqual(len(pd.concat(frames)),6)
            self.assertEqual(set(pd.concat(frames).model_version),{'v4a.0.1','v4b.0.1'})
            self.assertFalse((root/'dashboard/state').exists())
            self.assertTrue(all(not any(c.startswith('posterior_') for c in f) and 'q' not in f and 'r' not in f for f in frames))

    def test_workflow_visible_copy_matches_and_parallel_jobs_defined(self):
        workflow=(ROOT/'.github/workflows/forecasting.yml').read_text()
        self.assertEqual(workflow,(ROOT/'WORKFLOW_SETUP.yml').read_text())
        self.assertIn('matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}',workflow)
        self.assertIn('fail-fast: false',workflow)
        self.assertIn('save_and_export:',workflow)


if __name__=='__main__':unittest.main()

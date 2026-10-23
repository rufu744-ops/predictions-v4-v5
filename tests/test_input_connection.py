import importlib.util
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'models/v4a'))
sys.path.insert(0, str(ROOT / 'models/v4b'))
from v4a.data import load as load_a
from v4b.data import load as load_b


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


writer = module('v3_export_writer', ROOT / 'integration/v3_source/scripts/export_v4_inputs.py')
fixture = module('v4_connection_fixture', ROOT / 'models/v4a/demo.py')
checker = module('v4_input_checker', ROOT / 'tools/check_live_input.py')


class ConnectionTests(unittest.TestCase):
    def test_multiple_shards_preserve_all_ticker_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = fixture.make_input(root / 'fixture', 'JP', 1)
            calendar = pd.DataFrame({'market_close': data.sessions.close_at_utc.to_numpy()},
                                    index=pd.to_datetime(data.sessions.date))
            tickers = [f'T{i:03d}' for i in range(61)]
            prices = pd.concat([data.prices.assign(ticker=t) for t in tickers], ignore_index=True)
            features = pd.concat([data.features.assign(ticker=t) for t in tickers], ignore_index=True)
            meta = writer.publish_panel(root / 'feed', 'JP', calendar,
                prices.rename(columns={'adjusted_close': 'Close'}), features,
                data.columns, tickers, {}, synthetic=True)
            self.assertEqual(len(meta['files']['features']), 2)
            for loader in [load_a, load_b]:
                result = loader(root / 'feed', 'JP')
                self.assertEqual(len(result.features), len(features))
                self.assertEqual(set(result.features.ticker), set(tickers))

    def test_compressed_v3_export_loads_identically_in_a_b_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = fixture.make_input(root / 'fixture', 'US', 1)
            calendar = pd.DataFrame({'market_close': data.sessions.close_at_utc.to_numpy()},
                                    index=pd.to_datetime(data.sessions.date))
            quotes = data.prices.rename(columns={'adjusted_close': 'Close'})
            meta = writer.publish_panel(root / 'feed', 'US', calendar, quotes,
                data.features, data.columns, ['DEMO000'], {'base_set': 'M3'}, synthetic=True)
            a, b = load_a(root / 'feed', 'US'), load_b(root / 'feed', 'US')
            pd.testing.assert_frame_equal(a.features, b.features)
            self.assertEqual(a.digest, b.digest)
            self.assertEqual(a.columns, data.columns)
            self.assertEqual(len(a.features), len(data.features))
            path = root / 'feed' / meta['files']['features'][0]
            path.write_bytes(path.read_bytes() + b'corrupted')
            for loader in [load_a, load_b]:
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    loader(root / 'feed', 'US')

    def test_reader_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture.make_input(root, 'JP', 1)
            meta = json.loads((root / 'manifest.json').read_text())
            meta['files'] = {'sessions': ['../sessions.csv']}
            (root / 'manifest.json').write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                load_a(root, 'JP')

    def test_both_cli_runs_all_four_combinations_and_keeps_failure_status(self):
        calls = []
        def start(command, **kwargs):
            calls.append(command)
            return Mock(wait=Mock(return_value=1 if len(calls) == 1 else 0))
        with patch.object(sys, 'argv', ['run.py', '--market', 'both', '--model', 'both', '--demo']), \
             patch('subprocess.Popen', side_effect=start):
            with self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(ROOT / 'run.py'), run_name='__main__')
        self.assertEqual(exc.exception.code, 1)
        self.assertEqual(len(calls), 4)
        scopes = {(Path(c[1]).parent.name, c[c.index('--market') + 1]) for c in calls}
        self.assertEqual(scopes, {('v4a', 'JP'), ('v4b', 'JP'), ('v4a', 'US'), ('v4b', 'US')})

    def test_workflow_plan_both_and_scheduled_single_market(self):
        obj = yaml.safe_load((ROOT / 'WORKFLOW_SETUP.yml').read_text())
        script = obj['jobs']['plan']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as tmp:
            import os
            for event, market, expected in [('workflow_dispatch', 'BOTH', ['JP', 'US']),
                                             ('workflow_dispatch', 'JP', ['JP']),
                                             ('schedule', '', ['JP'])]:
                path = Path(tmp) / 'out'
                path.write_text('')
                env = dict(os.environ, EVENT=event, REQUESTED_MARKET=market,
                    REQUESTED_MODEL='both', REQUESTED_OPERATION='demo', REQUESTED_PROFILE='standard',
                    ENABLE_LIVE='', SCHEDULE='0 9 * * 1-5', GITHUB_OUTPUT=str(path))
                subprocess.run(['bash', '-c', script], env=env, check=True)
                result = dict(line.split('=', 1) for line in path.read_text().splitlines())
                self.assertEqual(json.loads(result['matrix']), {'model': ['a', 'b'], 'market': expected})
        self.assertEqual((ROOT / '.github/workflows/forecasting.yml').read_bytes(),
                         (ROOT / 'WORKFLOW_SETUP.yml').read_bytes())
        v3 = ROOT / 'integration/v3_source'
        source_workflow = yaml.safe_load((v3 / 'WORKFLOW_V4_INPUTS.yml').read_text())
        self.assertIn('export', source_workflow['jobs'])
        dispatch = source_workflow['jobs']['export']['steps'][-1]
        self.assertIn("steps.publish.outcome == 'success'", dispatch['if'])

    def test_preflight_explains_stale_input_and_reports_valid_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = fixture.make_input(root, 'US', 1)
            meta = json.loads((root / 'manifest.json').read_text())
            meta['synthetic'] = False  # local fixture only; never distributed as live data
            (root / 'manifest.json').write_text(json.dumps(meta))
            # The fixture includes later prices, so use a completed origin with all quotes.
            now = pd.Timestamp(data.sessions.close_at_utc.iloc[len(data.prices) - 1])
            text = checker.check(root, 'US', now=now)
            self.assertIn('ready stocks=1/1', text)
            later = data.sessions.close_at_utc.iloc[len(data.prices)]
            with self.assertRaisesRegex(ValueError, 'stale'):
                checker.check(root, 'US', now=later)


if __name__ == '__main__':
    unittest.main()

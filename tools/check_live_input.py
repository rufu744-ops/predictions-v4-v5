"""Report input freshness and the model's existing calibration requirements."""
import argparse
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'models/v4a'))
from v4a.data import load
from v4a.engine import observations, prepare_ticker


def check(folder, market, train_sessions=2520, now=None):
    data = load(folder, market)
    if data.manifest.get('synthetic', False):
        raise ValueError('Live mode requires real data')
    now = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    completed = data.sessions[data.sessions.close_at_utc <= now]
    if completed.empty:
        raise ValueError('No completed exchange session in input')
    cutoff = int(completed.index[-1])
    origin = data.sessions.date.iloc[cutoff]
    last_price = data.prices.date.max()
    if last_price != origin:
        raise ValueError(f'{market}: input is stale ({last_price}); latest completed session is {origin}. Run V3 input export first.')
    if len(data.sessions) <= cutoff + 20:
        raise ValueError('Calendar must extend 20 sessions beyond the origin')
    minimum = max(30, len(data.columns) + 5)
    ready = 0
    for ticker in data.manifest['expected_tickers']:
        price, features = prepare_ticker(data, ticker)
        if not np.isfinite(price[cutoff]) or not np.isfinite(features[cutoff]).any():
            continue
        good = True
        for h in [1, 5, 20]:
            _, y, steps = observations(price, features, cutoff, h)
            if len(y[steps >= max(0, cutoff - train_sessions + 1)]) < minimum:
                good = False
        ready += int(good)
    text = (f'{market}: origin={origin}, features={len(data.columns)}, train_sessions={train_sessions}, '
            f'minimum matured outcomes per horizon={minimum}, '
            f'ready stocks={ready}/{len(data.manifest["expected_tickers"])}. '
            'The model enforces 95% coverage; an exported file alone does not guarantee enough history.')
    print(text, flush=True)
    return text


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--market', choices=['JP', 'US'], required=True)
    p.add_argument('--train-sessions', type=int, default=2520)
    a = p.parse_args()
    check(a.input, a.market, a.train_sessions)

from pathlib import Path
import hashlib
import json

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def bundles(folder):
    for p in sorted(Path(folder).glob('*.json')):
        meta=json.loads(p.read_text());csv=p.with_suffix('.csv')
        if meta.get('csv_file')!=csv.name or not csv.exists() or digest(csv)!=meta.get('csv_sha256'):
            raise ValueError(f'Changed/incomplete log: {p.name}')
        yield csv,meta

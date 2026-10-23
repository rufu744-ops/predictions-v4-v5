"""Compressed posterior state checkpoints; stay in the private model account."""
from pathlib import Path
import hashlib
import json
import os
import numpy as np

ARRAYS=['log_ratios','weights','log_weights','means','covariances','shapes','scales']


def save_checkpoint(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    archive=path.with_suffix('.npz');tmp=path.with_suffix('.npz.tmp')
    bank=obj['bank'];arrays={name:bank[name] for name in ARRAYS}
    with tmp.open('wb') as f:np.savez_compressed(f,**arrays)
    os.replace(tmp,archive)
    meta=dict(obj,bank={k:v for k,v in bank.items() if k not in ARRAYS},
        arrays_file=archive.name,arrays_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(meta,allow_nan=False,separators=(',',':')))
    os.replace(tmp,path)


def load_checkpoint(path):
    path=Path(path)
    if not path.exists():return None
    meta=json.loads(path.read_text());archive=path.with_suffix('.npz')
    if not archive.exists() or meta.get('arrays_file')!=archive.name or hashlib.sha256(archive.read_bytes()).hexdigest()!=meta.get('arrays_sha256'):
        # A checkpoint is disposable; immutable forecast logs remain strictly verified.
        return None
    with np.load(archive,allow_pickle=False) as data:
        meta['bank'].update({name:data[name].copy() for name in ARRAYS})
    return meta

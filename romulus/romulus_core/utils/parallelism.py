from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict
from .yaml_io import read_yaml

DEFAULTS: Dict[str, Any] = {
    "gpu": True,
    "gpu_backend": "cuda",
    "n_jobs": 8,
    "fastmath": True,
    "use_numba": True,
    "omp_num_threads": 8,
    "mkl_num_threads": 8,
}

def configure(hardware_yaml: str | Path) -> Dict[str, Any]:
    cfg = DEFAULTS.copy()
    try:
        cfg.update(read_yaml(hardware_yaml) or {})
    except FileNotFoundError:
        pass

    os.environ["OMP_NUM_THREADS"] = str(cfg["omp_num_threads"])
    os.environ["MKL_NUM_THREADS"] = str(cfg["mkl_num_threads"])
    # LightGBM/XGB pick up GPU automatically if CUDA present; we only expose config knobs here.
    return cfg


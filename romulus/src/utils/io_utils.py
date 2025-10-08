# romulus/src/utils/io_utils.py
# Lightweight IO helpers used across the pipeline.

import os
import json
import hashlib
from typing import Any, Dict

import yaml

def ensure_dir(path: str) -> None:
    """Create directory if it doesn’t exist (recursively)."""
    if not path:
        return
    os.makedirs(path, exist_ok=True)

def append_jsonl(path: str, obj: dict) -> None:
    """Append one JSON object per line (for logs/provenance)."""
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def load_configs(base_path: str = "config/config.yaml") -> Dict[str, Any]:
    """Load global configuration YAML safely."""
    try:
        with open(base_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg
    except FileNotFoundError:
        print(f"Warning: config file not found at {base_path}")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def load_yaml(path: str) -> Dict[str, Any]:
    """Load an arbitrary YAML file into a dict (empty dict on error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading YAML {path}: {e}")
        return {}

def save_yaml(obj: Dict[str, Any], path: str) -> None:
    """Write a dict to YAML (atomic-ish by temp file then rename)."""
    ensure_dir(os.path.dirname(path))
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(obj, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)

def dict_sha256(obj: Dict[str, Any]) -> str:
    """Deterministic SHA256 of a dict for snapshot filenames."""
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def save_json(obj: dict, path: str) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def set_global_seed(seed: int = 42) -> None:
    import random, numpy as np
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:
        pass
    random.seed(seed)
    np.random.seed(seed)


from __future__ import annotations
import hashlib
import json
from typing import Any, Dict

def stable_hash(obj: Dict[str, Any]) -> str:
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

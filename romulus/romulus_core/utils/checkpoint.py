from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from .paths import ARTF, ensure_dirs
from .hashing import stable_hash

def save_state(stage: str, payload: Dict[str, Any] | None = None) -> Path:
    ensure_dirs()
    state = {
        "stage": stage,
        "payload": payload or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    h = stable_hash(state)
    out = ARTF / "state.json"
    out.write_text(json_dump(state), encoding="utf-8")
    (ARTF / "state.history" / f"{h}.json").parent.mkdir(parents=True, exist_ok=True)
    (ARTF / "state.history" / f"{h}.json").write_text(json_dump(state), encoding="utf-8")
    return out

def json_dump(d: Dict[str, Any]) -> str:
    import json
    return json.dumps(d, indent=2, sort_keys=True, default=str)

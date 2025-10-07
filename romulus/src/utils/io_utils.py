import os
import json

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

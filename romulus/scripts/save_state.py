from __future__ import annotations
from romulus_core.utils.checkpoint import save_state
from romulus_core.utils.paths import ensure_dirs

if __name__ == "__main__":
    ensure_dirs()
    out = save_state(stage="scaffold_ready", payload={"ok": True})
    print(f"State saved to: {out}")


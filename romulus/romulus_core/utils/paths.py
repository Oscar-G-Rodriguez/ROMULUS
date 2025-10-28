from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJ = ROOT / "projects" / "default"
CONF = PROJ / "config"
ARTF = PROJ / "artifacts"

def ensure_dirs() -> None:
    for p in [CONF, ARTF, ARTF / "datasets", ARTF / "features", ARTF / "labels", ARTF / "cv",
              ARTF / "models", ARTF / "reports", ARTF / "regimes"]:
        p.mkdir(parents=True, exist_ok=True)



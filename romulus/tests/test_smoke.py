from romulus_core.utils.logger import get_logger
from romulus_core.utils.parallelism import configure
from romulus_core.utils.paths import ensure_dirs

def test_smoke():
    ensure_dirs()
    log = get_logger("test")
    cfg = configure("romulus_core/hardware/hardware.yaml")
    assert isinstance(cfg, dict)
    log.info("Smoke OK")


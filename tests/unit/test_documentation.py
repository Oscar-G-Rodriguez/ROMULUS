"""Keep public documentation examples and referenced files reproducible."""

from pathlib import Path
import re

from romulus.config.schema import load_suite_config


ROOT = Path(__file__).resolve().parents[2]


def test_readme_relative_links_exist() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", readme)
    local_links = [link.split("#", 1)[0] for link in links if "://" not in link and not link.startswith("#")]
    assert local_links
    assert not [link for link in local_links if not (ROOT / link).exists()]


def test_checked_in_default_suite_is_valid_and_meta_enabled() -> None:
    config = load_suite_config(ROOT / "configs" / "suite_default.yaml")
    assert config.meta.enabled is True
    assert config.data.coverage_policy == "dynamic"


def test_declared_license_file_exists() -> None:
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")

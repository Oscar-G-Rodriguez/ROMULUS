"""Unit tests for CLI helpers."""

from __future__ import annotations

from pathlib import Path

from romulus.cli.main import _default_suite_template, resolve_default_config_path
from romulus.config.schema import SuiteConfig

import yaml


def test_resolver_env_precedence(tmp_path) -> None:
    env_config = tmp_path / "env.yaml"
    env_config.write_text("test", encoding="utf-8")

    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    default_config = configs_dir / "etf_equal_weight.yaml"
    default_config.write_text("test", encoding="utf-8")

    resolved = resolve_default_config_path(
        cwd=tmp_path,
        env={"ROMULUS_CONFIG": str(env_config)},
    )

    assert resolved == env_config


def test_resolver_cwd_default(tmp_path) -> None:
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    default_config = configs_dir / "etf_equal_weight.yaml"
    default_config.write_text("test", encoding="utf-8")

    resolved = resolve_default_config_path(cwd=tmp_path, env={})

    assert resolved == default_config


def test_resolver_returns_none_when_missing(tmp_path) -> None:
    resolved = resolve_default_config_path(cwd=tmp_path, env={})

    assert resolved is None


def test_generated_suite_template_enables_meta_and_all_default_candidates() -> None:
    config = SuiteConfig.model_validate(yaml.safe_load(_default_suite_template()))
    names = {item.name for item in config.strategies}

    assert config.meta.enabled is True
    assert config.meta.selection_day == "friday"
    assert {"buy_and_hold", "ma_crossover", "ml_return_xgb", "ml_vol_xgb", "ml_rar_xgb", "ml_rar_ridge"} <= names

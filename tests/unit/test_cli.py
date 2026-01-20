"""Unit tests for CLI helpers."""

from __future__ import annotations

from pathlib import Path

from romulus.cli.main import resolve_default_config_path


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

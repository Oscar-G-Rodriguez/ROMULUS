"""Runtime metadata and XGBoost device diagnostics."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from time import perf_counter
from typing import Iterable, Mapping, Optional

import numpy as np


_LAST_XGBOOST_DIAGNOSTIC: Optional[dict] = None


def _distribution_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _uv_version() -> Optional[str]:
    executable = os.environ.get("UV") or shutil.which("uv")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout.strip()
    return output.removeprefix("uv ") or None


def _training_devices(decision_logs: Iterable[Mapping[str, object]]) -> list[str]:
    devices: set[str] = set()
    for row in decision_logs:
        training_info = row.get("training_info")
        if not isinstance(training_info, Mapping):
            continue
        device = training_info.get("device")
        if device:
            devices.add(str(device))
    return sorted(devices)


def collect_runtime_info(
    decision_logs: Iterable[Mapping[str, object]] = (),
) -> dict:
    """Return reproducibility metadata suitable for a run manifest."""
    devices = _training_devices(decision_logs)
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "uv_version": _uv_version(),
        "xgboost_version": _distribution_version("xgboost"),
        "execution_devices": devices or ["cpu"],
        "last_xgboost_diagnostic": _LAST_XGBOOST_DIAGNOSTIC,
    }


def _booster_device(booster: object) -> str:
    config = json.loads(booster.save_config())
    return str(config["learner"]["generic_param"]["device"])


def _diagnostic_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(512, 8)).astype(np.float32)
    y = (0.6 * X[:, 0] - 0.25 * X[:, 1] + 0.1 * X[:, 2]).astype(np.float32)
    return X, y


def _standard_attempt(xgb: object, X: np.ndarray, y: np.ndarray, device: str) -> dict:
    started = perf_counter()
    matrix = xgb.DMatrix(X, y)
    booster = xgb.train(
        {
            "objective": "reg:squarederror",
            "tree_method": "hist",
            "device": device,
            "max_depth": 3,
            "eta": 0.1,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "seed": 42,
            "nthread": 1,
        },
        matrix,
        num_boost_round=16,
    )
    predictions = booster.predict(xgb.DMatrix(X[:16]))
    actual_device = _booster_device(booster)
    if not np.isfinite(predictions).all():
        raise RuntimeError("XGBoost produced non-finite diagnostic predictions")
    if device.startswith("cuda") and not actual_device.startswith("cuda"):
        raise RuntimeError(f"XGBoost reported {actual_device!r} after CUDA was requested")
    return {
        "mode": "cuda" if device.startswith("cuda") else "cpu",
        "status": "passed",
        "actual_device": actual_device,
        "elapsed_seconds": perf_counter() - started,
        "prediction_checksum": float(np.sum(predictions)),
    }


def _memory_conscious_cuda_attempt(xgb: object, X: np.ndarray, y: np.ndarray) -> dict:
    started = perf_counter()
    matrix = xgb.QuantileDMatrix(X, y, max_bin=64)
    booster = xgb.train(
        {
            "objective": "reg:squarederror",
            "tree_method": "hist",
            "device": "cuda:0",
            "max_bin": 64,
            "max_depth": 2,
            "eta": 0.1,
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "seed": 42,
            "nthread": 1,
        },
        matrix,
        num_boost_round=8,
    )
    predictions = booster.predict(matrix)[:16]
    actual_device = _booster_device(booster)
    if not np.isfinite(predictions).all():
        raise RuntimeError("XGBoost produced non-finite CUDA retry predictions")
    if not actual_device.startswith("cuda"):
        raise RuntimeError(f"XGBoost reported {actual_device!r} after CUDA was requested")
    return {
        "mode": "cuda_memory_conscious",
        "status": "passed",
        "actual_device": actual_device,
        "elapsed_seconds": perf_counter() - started,
        "prediction_checksum": float(np.sum(predictions)),
    }


def run_xgboost_device_diagnostic() -> dict:
    """Try CUDA, retry CUDA conservatively, then verify CPU XGBoost."""
    global _LAST_XGBOOST_DIAGNOSTIC

    started = perf_counter()
    result = {
        "requested_device": "cuda:0",
        "xgboost_version": _distribution_version("xgboost"),
        "status": "unavailable",
        "actual_device": None,
        "attempts": [],
    }
    try:
        import xgboost as xgb
    except Exception as exc:
        result["attempts"].append(
            {"mode": "import", "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        )
        result["elapsed_seconds"] = perf_counter() - started
        _LAST_XGBOOST_DIAGNOSTIC = result
        return result

    X, y = _diagnostic_data()
    attempts = (
        ("cuda", lambda: _standard_attempt(xgb, X, y, "cuda:0")),
        ("cuda_memory_conscious", lambda: _memory_conscious_cuda_attempt(xgb, X, y)),
        ("cpu", lambda: _standard_attempt(xgb, X, y, "cpu")),
    )
    for mode, attempt in attempts:
        try:
            attempt_result = attempt()
            result["attempts"].append(attempt_result)
            result["status"] = mode
            result["actual_device"] = attempt_result["actual_device"]
            break
        except Exception as exc:
            result["attempts"].append(
                {"mode": mode, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            )

    result["elapsed_seconds"] = perf_counter() - started
    _LAST_XGBOOST_DIAGNOSTIC = result
    return result

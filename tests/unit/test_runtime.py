"""Runtime metadata and device-diagnostic tests."""

from __future__ import annotations

import sys

import romulus.runtime as runtime


def test_collect_runtime_info_reports_environment(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_uv_version", lambda: "test-uv")
    monkeypatch.setattr(runtime, "_distribution_version", lambda name: "test-xgb" if name == "xgboost" else None)

    info = runtime.collect_runtime_info(
        [{"training_info": {"device": "cuda:0"}}, {"training_info": {"device": "cpu"}}]
    )

    assert info["python_version"] == ".".join(map(str, sys.version_info[:3]))
    assert info["uv_version"] == "test-uv"
    assert info["xgboost_version"] == "test-xgb"
    assert info["execution_devices"] == ["cpu", "cuda:0"]


def test_device_diagnostic_falls_back_to_cpu(monkeypatch) -> None:
    class FakeXGBoost:
        pass

    monkeypatch.setitem(sys.modules, "xgboost", FakeXGBoost())
    monkeypatch.setattr(runtime, "_distribution_version", lambda _name: "test-xgb")
    monkeypatch.setattr(runtime, "_diagnostic_data", lambda: (object(), object()))

    def fake_standard(_xgb, _X, _y, device):
        if device.startswith("cuda"):
            raise RuntimeError("no CUDA")
        return {"mode": "cpu", "status": "passed", "actual_device": "cpu"}

    monkeypatch.setattr(runtime, "_standard_attempt", fake_standard)
    monkeypatch.setattr(
        runtime,
        "_memory_conscious_cuda_attempt",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("CUDA retry failed")),
    )

    result = runtime.run_xgboost_device_diagnostic()

    assert result["status"] == "cpu"
    assert result["actual_device"] == "cpu"
    assert [attempt["status"] for attempt in result["attempts"]] == ["failed", "failed", "passed"]

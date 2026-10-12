import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.capture import CaptureTarget, load_targets
from nsight_agent.core import NsightError, NsightService


@pytest.fixture
def configured(tmp_path, monkeypatch):
    registry = tmp_path / "中文 targets.toml"
    registry.write_text(
        "[targets.example]\ncommand = "
        + json.dumps([sys.executable, "workload.py", "a; echo b"])
        + "\ncwd = "
        + json.dumps(str(tmp_path))
        + "\nduration_seconds = 2\ntimeout_seconds = 30\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NSIGHT_CAPTURE_CONFIG", str(registry))
    return NsightService(cache_dir=tmp_path / "cache")


def test_collection_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NSIGHT_CAPTURE_CONFIG", raising=False)
    service = NsightService()
    assert service.capture_targets()["status"] == "not_configured"
    with pytest.raises(NsightError) as error:
        service.capture("python anything")
    assert error.value.code == "CAPTURE_TARGET_UNKNOWN"


@pytest.mark.parametrize("policy", ["true", "sigkill"])
def test_fixed_collection_args_and_registered_result(configured, monkeypatch, policy):
    seen = []

    def run(args, cwd):
        seen.append((args, cwd, configured.timeout))
        if args == ["--version"]:
            return "2025.6.3"
        if args == ["profile", "--help"]:
            return (
                "--trace --sample --cpuctxsw --duration --output\n--kill=\n Values '"
                + policy
                + "'\n"
            )
        output = next(a for a in args if a.startswith("--output=")).split("=", 1)[1]
        Path(output).with_suffix(".nsys-rep").write_bytes(b"measured report placeholder")
        return "application console output is not returned"

    monkeypatch.setattr(configured, "_run", run)
    result = configured.capture("example")
    args, cwd, timeout = seen[-1]
    assert args[:4] == ["profile", "--trace=cuda,nvtx", "--sample=none", "--cpuctxsw=none"]
    assert f"--kill={policy}" in args and "--duration=2" in args
    assert args[-3:] == [sys.executable, "workload.py", "a; echo b"]
    assert cwd == configured.cache.parent and timeout == 30
    assert configured.timeout == 120
    assert result["report_id"] in configured.reports
    assert Path(result["path"]).is_relative_to(configured.cache)
    assert "force-overwrite" not in str(args)


def test_unknown_target_never_runs(configured, monkeypatch):
    monkeypatch.setattr(configured, "_run", lambda *a: pytest.fail("unexpected execution"))
    with pytest.raises(NsightError) as error:
        configured.capture("example --shell")
    assert error.value.code == "CAPTURE_TARGET_UNKNOWN"


def test_capture_failure_does_not_register_partial_report(configured, monkeypatch):
    def run(args, cwd):
        if args == ["--version"]:
            return "version"
        if args == ["profile", "--help"]:
            return "--trace --sample --cpuctxsw --duration --output\n--kill= 'true'"
        raise NsightError("Nsight exceeded 30s")

    monkeypatch.setattr(configured, "_run", run)
    with pytest.raises(NsightError, match="exceeded"):
        configured.capture("example")
    assert not configured.reports and configured.timeout == 120


@pytest.mark.parametrize("text", ["bad=[", "[targets.x]\ncommand='python'", "other=1"])
def test_invalid_registry_is_actionable(tmp_path, monkeypatch, text):
    path = tmp_path / "targets.toml"
    path.write_text(text)
    monkeypatch.setenv("NSIGHT_CAPTURE_CONFIG", str(path))
    with pytest.raises(NsightError) as error:
        load_targets()
    assert error.value.code == "CAPTURE_CONFIG_INVALID" and error.value.recovery


@pytest.mark.parametrize(
    "values",
    [
        {"duration_seconds": 121},
        {"timeout_seconds": 301},
        {"cwd": "."},
        {"command": ["python"]},
        {"command": ["/python", "bad\x00arg"]},
        {"extra_args": ["--output=arbitrary"]},
        {"duration_seconds": 30, "timeout_seconds": 30},
    ],
)
def test_registry_bounds(tmp_path, values):
    with pytest.raises(ValidationError):
        CaptureTarget(**{"command": [sys.executable], "cwd": str(tmp_path), **values})

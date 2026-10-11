import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.core import (
    REPORTS,
    NsightError,
    NsightService,
    Query,
    parse_csv,
    run_process,
    time_argument,
)

SUMMARY = """Time (%),Total Time (ns),Instances,Avg (ns),Med (ns),Min (ns),Max (ns),StdDev (ns),Name
75.0,3000,3,1000,1000,800,1200,200,"gemm<float, float>"
25.0,1000,2,500,500,400,600,100,vector_add
"""
TRACE = """Start (ns),Duration (ns),GrdX,Device,Strm,Name
9007199254740993,1000,32,Test GPU (0),7,"gemm<float, float>"
9007199254740994,200,,Test GPU (0),7,[CUDA memcpy HtoD]
"""


@pytest.fixture
def service(tmp_path, monkeypatch):
    executable = tmp_path / "nsys.exe"
    executable.touch()
    svc = NsightService(str(executable), tmp_path / "cache")
    svc._capabilities = {
        "version": "2025.6.3",
        "reports": list(REPORTS.values()),
        "nsys_path": str(executable),
        "options": [
            "--report",
            "--format",
            "--output",
            "--quiet",
            "--filter-time",
            "--filter-nvtx",
        ],
    }
    monkeypatch.setattr(
        svc, "_run", lambda args, cwd: TRACE if "cuda_gpu_trace" in args else SUMMARY
    )
    source = tmp_path / "中文 空格.sqlite"
    source.write_bytes(b"synthetic placeholder; never passed to real Nsight")
    svc.test_source = source
    svc.test_id = svc.open_report(str(source))["report_id"]
    return svc


def test_summary_preserves_denominator_and_source(service):
    before = service.test_source.read_bytes()
    result = service.query(service.test_id, "kernel_summary", Query(name_contains="VECTOR"))
    assert result["rows"][0]["Time (%)"] == 25.0
    assert result["total_rows"] == 1
    assert result["rows"][0]["Total Time (ns)"] == 1000
    assert service.test_source.read_bytes() == before
    assert Path(result["provenance"]["arguments"][-1]) != service.test_source


def test_pagination_and_sort(service):
    first = service.query(service.test_id, "kernel_summary", Query(limit=1, descending=False))
    assert first["rows"][0]["Name"] == "vector_add"
    assert first["next_offset"] == 1
    second = service.query(
        service.test_id, "kernel_summary", Query(limit=1, descending=False, offset=1)
    )
    assert second["next_offset"] is None
    assert "gemm" in second["rows"][0]["Name"]


def test_no_matches(service):
    result = service.query(service.test_id, "kernel_summary", Query(name_contains="absent"))
    assert result["rows"] == [] and result["next_offset"] is None


def test_trace_excludes_memcpy_preserves_large_int(service):
    result = service.query(service.test_id, "kernel_trace")
    assert result["total_rows"] == 1
    assert result["rows"][0]["Start (ns)"] == 9007199254740993
    assert result["rows"][0]["Strm"] == 7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"nvtx": "step", "start_ns": 0},
        {"start_ns": 2, "end_ns": 1},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"nvtx": ""},
        {"unknown": 1},
    ],
)
def test_invalid_query(kwargs):
    with pytest.raises(ValidationError):
        Query(**kwargs)


def test_filters_forward_exactly(service):
    time = service.query(service.test_id, "kernel_summary", Query(start_ns=0, end_ns=2000))
    assert "--filter-time=0.000000000s/0.000002000s" in time["provenance"]["arguments"]
    nvtx = service.query(service.test_id, "kernel_summary", Query(nvtx="step name@domain/2"))
    assert "--filter-nvtx=step name@domain/2" in nvtx["provenance"]["arguments"]


def test_capability_error(service):
    service._capabilities["options"].remove("--filter-time")
    with pytest.raises(NsightError, match="Unsupported Nsight options"):
        service.query(service.test_id, "kernel_summary", Query(start_ns=0))
    service._capabilities["reports"] = []
    with pytest.raises(NsightError, match="does not support"):
        service.query(service.test_id, "kernel_summary")


def test_unknown_sort_and_report(service):
    with pytest.raises(NsightError, match="Unknown sort"):
        service.query(service.test_id, "kernel_summary", Query(sort_by="invalid"))
    with pytest.raises(NsightError, match="Unknown report_id"):
        service.query("invalid", "kernel_summary")


def test_changed_report(service):
    service.test_source.write_bytes(b"changed")
    with pytest.raises(NsightError, match="changed since"):
        service.query(service.test_id, "kernel_summary")


def test_invalid_and_empty_reports(service, tmp_path):
    empty = tmp_path / "empty.nsys-rep"
    empty.touch()
    with pytest.raises(NsightError, match="empty"):
        service.open_report(str(empty))
    with pytest.raises(NsightError, match="existing"):
        service.open_report(str(tmp_path / "missing.sqlite"))


@pytest.mark.parametrize(
    "text", ["", "SKIPPED: no CUDA data", "Name,A\nx,1,2\n", "Name,Name\nx,y\n"]
)
def test_invalid_csv(text):
    with pytest.raises(NsightError):
        parse_csv(text)


def test_header_only_csv():
    columns, rows = parse_csv("Name,Total Time (ns)\n")
    assert columns and rows == []


def test_process_errors(tmp_path, monkeypatch):
    executable = tmp_path / "nsys.exe"
    executable.touch()
    svc = NsightService(str(executable), tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr("nsight_agent.core.run_process", timeout)
    with pytest.raises(NsightError, match="exceeded"):
        svc._run(["--version"], tmp_path)
    monkeypatch.setattr(
        "nsight_agent.core.run_process",
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", "incompatible report"),
    )
    with pytest.raises(NsightError, match="incompatible report"):
        svc._run(["--version"], tmp_path)
    monkeypatch.setattr(
        "nsight_agent.core.run_process",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", "SKIPPED: missing CUDA"),
    )
    with pytest.raises(NsightError, match="missing CUDA"):
        svc._run(["--version"], tmp_path)


def test_safe_process_arguments(tmp_path, monkeypatch):
    executable = tmp_path / "nsys.exe"
    executable.touch()
    monkeypatch.setenv("NSYS_STATS_REPORT_PATH", "untrusted")
    monkeypatch.setenv("PYTHONPATH", "untrusted")

    def check(args, **kwargs):
        assert isinstance(args, list)
        assert "NSYS_STATS_REPORT_PATH" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "version", "")

    monkeypatch.setattr("nsight_agent.core.run_process", check)
    assert NsightService(str(executable))._run(["--version"], tmp_path) == "version"


def test_memory_size(service, monkeypatch):
    monkeypatch.setattr(
        service, "_run", lambda *a: "Total (B),Count,Operation\n4096,1,[CUDA memcpy HtoD]\n"
    )
    result = service.memory_summary(service.test_id, "size")
    assert result["rows"][0]["Total (B)"] == 4096
    assert result["official_report"] == "cuda_gpu_mem_size_sum"


def test_time_argument_large_negative_and_open():
    assert time_argument(10_000_000_001) == "10.000000001s"
    assert time_argument(-1) == "-0.000000001s"
    assert time_argument(None) == ""


def test_actual_process_timeout(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            env=os.environ.copy(),
            timeout=0.2,
        )


def test_help_reports_exit_one(tmp_path, monkeypatch):
    executable = tmp_path / "nsys.exe"
    executable.touch()
    message = "The following built-in reports are available:\n  cuda_api_sum -- CUDA API Summary\n"
    monkeypatch.setattr(
        "nsight_agent.core.run_process",
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, message, ""),
    )
    svc = NsightService(str(executable))
    assert svc._run(["stats", "--help-reports"], tmp_path) == message
    with pytest.raises(NsightError):
        svc._run(["stats", "--report", "cuda_api_sum"], tmp_path)

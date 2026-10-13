"""Diagnostic contracts without a GPU: official schemas, bounds and incomplete evidence."""

import csv
import io
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from nsight_agent.core import NsightError, NsightService, Query
from nsight_agent.diagnostics import RULES, DiagnosticOptions, diagnostic_csv


def table(rule, count=3):
    columns = list(RULES[rule].columns)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for index in range(count):
        values = {c: 1 for c in columns}
        values.update(
            {
                "Start (ns)": 9007199254740993 + index,
                "Duration (ns)": 30 - index,
                "API Name": "cudaStreamSynchronize_v3020",
                "Src Kind": "Pageable",
                "Dst Kind": "Device",
                "Memory Kind": "Unified",
                "In-Use (%)": 123.4,
            }
        )
        writer.writerow({c: values[c] for c in columns})
    return stream.getvalue()


@pytest.fixture
def diagnostic(tmp_path, monkeypatch):
    svc = NsightService(cache_dir=tmp_path / "中文 缓存")
    source = tmp_path / "中文 原报告.sqlite"
    source.write_bytes(b"unchanged report placeholder")
    rid = svc.open_report(str(source))["report_id"]
    svc._analysis_capabilities = {
        "version": "2025.6.3",
        "nsys_path": "nsys",
        "options": ["--rule", "--format", "--output", "--quiet", "--filter-time", "--filter-nvtx"],
        "rules": [{"rule": r, "available": True} for r in RULES],
        "rule_parameters": {r: ["rows", "gap", "threshold", "chunks"] for r in RULES},
    }
    calls = []

    def run(args, cwd):
        calls.append((args, cwd))
        return table(args[2].split(":")[0])

    monkeypatch.setattr(svc, "_run", run)
    return svc, rid, source, calls


@pytest.mark.parametrize("rule", list(RULES))
def test_all_rule_schemas_and_evidence(diagnostic, rule):
    svc, rid, source, calls = diagnostic
    result = svc.analyze(rid, rule, Query(limit=1))
    assert result["status"] == "findings" and result["total_rows"] == 3
    assert result["next_offset"] == 1
    row = result["rows"][0]
    assert row["Start (ns)"] == 9007199254740993
    assert row["time_query"]["end_ns"] == 9007199254741023
    assert ":rows=-1" in calls[-1][0][2]
    assert Path(calls[-1][0][-1]) != source
    assert source.read_bytes() == b"unchanged report placeholder"
    assert result["official_rule"] == rule and result["nsight_version"] == "2025.6.3"
    assert result["rule_parameters"]["rows"] == -1
    assert result["units"]["memory"] == "B"
    if rule == "gpu_time_util":
        assert row["In-Use (%)"] == 123.4  # Never clamp concurrent operation time to 100%.


def test_full_findings_then_filter_and_paginate(diagnostic, monkeypatch):
    svc, rid, _, _ = diagnostic
    monkeypatch.setattr(svc, "_run", lambda args, cwd: table("cuda_api_sync", 205))
    first = svc.analyze(rid, "cuda_api_sync", Query(limit=200))
    assert first["total_rows"] == 205 and first["next_offset"] == 200
    last = svc.analyze(rid, "cuda_api_sync", Query(offset=200, limit=200))
    assert len(last["rows"]) == 5 and last["next_offset"] is None
    empty = svc.analyze(rid, "cuda_api_sync", Query(name_contains="unmatched"))
    assert empty["status"] == "no_findings" and empty["official_findings"] == 205
    beyond = svc.analyze(rid, "cuda_api_sync", Query(offset=300))
    assert beyond["status"] == "findings" and beyond["rows"] == []


@pytest.mark.parametrize("output", ["", " \n", "Duration (ns),Start (ns),PID,TID,API Name\n"])
def test_no_findings_is_exportable_not_missing_data(diagnostic, monkeypatch, output):
    svc, rid, _, _ = diagnostic
    monkeypatch.setattr(svc, "_run", lambda args, cwd: output)
    result = svc.analyze(rid, "cuda_api_sync")
    assert result["status"] == "no_findings" and result["rows"] == []
    for format in ("json", "markdown"):
        export = svc.export_analysis([result["result_id"]], format)
        assert "no_findings" in Path(export["path"]).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "output",
    [
        "unexpected log\n",
        "Duration (ns),API Name\n1,x\n",
        "Duration (ns),Start (ns),PID,TID,API Name\n1,2,3,4,x,extra\n",
    ],
)
def test_bad_schema_is_not_no_findings(diagnostic, monkeypatch, output):
    svc, rid, _, _ = diagnostic
    monkeypatch.setattr(svc, "_run", lambda args, cwd: output)
    with pytest.raises(NsightError) as error:
        svc.analyze(rid, "cuda_api_sync")
    assert error.value.code == "UNSUPPORTED_SCHEMA"


def test_exclusive_scopes_and_fixed_parameters(diagnostic):
    svc, rid, _, calls = diagnostic
    result = svc.analyze(
        rid, "gpu_gaps", Query(start_ns=0, end_ns=100), DiagnosticOptions(gap_ms=1)
    )
    assert "--filter-time=0.000000000s/0.000000100s" in calls[-1][0]
    assert result["rule_parameters"] == {"rows": -1, "gap": 1}
    svc.analyze(
        rid,
        "gpu_time_util",
        Query(nvtx="Train/0"),
        DiagnosticOptions(threshold_percent=90, chunks=10),
    )
    assert "--filter-nvtx=Train/0" in calls[-1][0]
    assert calls[-1][0][2] == "gpu_time_util:rows=-1:threshold=90:chunks=10"
    with pytest.raises(ValidationError):
        Query(nvtx="Train", start_ns=1)


@pytest.mark.parametrize(
    "options",
    [
        {"gap_ms": -1},
        {"gap_ms": 60001},
        {"threshold_percent": 101},
        {"chunks": 0},
        {"chunks": 1001},
        {"script": "custom"},
        {"rows": 1},
    ],
)
def test_option_boundaries(options):
    with pytest.raises(ValidationError):
        DiagnosticOptions(**options)


@pytest.mark.parametrize(
    "rule,query,options",
    [
        ("dx12_mem_ops", Query(), DiagnosticOptions()),
        ("cuda_api_sync:rows=-1", Query(), DiagnosticOptions()),
        ("cuda_api_sync", Query(), DiagnosticOptions(gap_ms=1)),
        ("gpu_gaps", Query(), DiagnosticOptions(chunks=10)),
        ("gpu_gaps", Query(name_contains="x"), DiagnosticOptions()),
        ("cuda_api_sync", Query(sort_by="injected"), DiagnosticOptions()),
    ],
)
def test_reject_unsupported_input_before_execution(diagnostic, rule, query, options):
    svc, rid, _, calls = diagnostic
    with pytest.raises(NsightError):
        svc.analyze(rid, rule, query, options)
    assert calls == []


@pytest.mark.parametrize("missing", ["rule", "--filter-time", "rows", "gap"])
def test_installed_compatibility_errors(diagnostic, missing):
    svc, rid, _, calls = diagnostic
    cap = svc._analysis_capabilities
    if missing == "rule":
        next(r for r in cap["rules"] if r["rule"] == "gpu_gaps")["available"] = False
    elif missing.startswith("--"):
        cap["options"].remove(missing)
    else:
        cap["rule_parameters"]["gpu_gaps"].remove(missing)
    with pytest.raises(NsightError) as error:
        svc.analyze(rid, "gpu_gaps", Query(start_ns=0))
    assert error.value.code == "CAPABILITY_UNAVAILABLE" and calls == []


def test_rule_discovery_excludes_other_installed_scripts(tmp_path, monkeypatch):
    executable = tmp_path / "nsys"
    executable.touch()
    svc = NsightService(str(executable), tmp_path / "cache")

    def run(args, cwd):
        if args == ["--version"]:
            return "2025.6.3"
        if args == ["analyze", "--help"]:
            return "--rule --format --output --quiet --filter-time --filter-nvtx"
        if args == ["analyze", "--help-rules"]:
            return "  gpu_gaps[:args] -- GPU Gaps\n  custom_rule -- Custom\n"
        return "    rows=<limit>\n    gap=<threshold>\n"

    monkeypatch.setattr(svc, "_run", run)
    result = svc.analysis_rules()
    assert len(result["rules"]) == 6
    assert [r["rule"] for r in result["rules"] if r["available"]] == ["gpu_gaps"]
    assert "custom_rule" not in result["rule_parameters"]


@pytest.mark.parametrize("kind", ["missing", "warning", "failed", "timeout"])
def test_real_runner_diagnostics(diagnostic, monkeypatch, kind):
    svc, rid, _, _ = diagnostic
    # Retain real _run error classification rather than merely throwing fixture exceptions.
    monkeypatch.setattr(svc, "_run", NsightService._run.__get__(svc))
    monkeypatch.setattr("nsight_agent.core.discover_nsys", lambda explicit: Path("nsys"))

    def process(args, **kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(args, 120)
        if kind == "missing":
            return subprocess.CompletedProcess(args, 0, "", "[SKIPPED] required CUDA data absent")
        return subprocess.CompletedProcess(
            args, 1 if kind == "failed" else 0, table("cuda_api_sync"), "WARNING: compatibility"
        )

    monkeypatch.setattr("nsight_agent.core.run_process", process)
    if kind == "warning":
        assert svc.analyze(rid, "cuda_api_sync")["warnings"]
    else:
        with pytest.raises(NsightError) as error:
            svc.analyze(rid, "cuda_api_sync")
        assert (
            error.value.code
            == {
                "missing": "MISSING_DATA",
                "failed": "COMMAND_FAILED",
                "timeout": "TIMEOUT",
            }[kind]
        )


def test_official_help_exit_one_is_narrowly_accepted(tmp_path, monkeypatch):
    svc = NsightService(cache_dir=tmp_path)
    monkeypatch.setattr("nsight_agent.core.discover_nsys", lambda explicit: Path("nsys"))
    monkeypatch.setattr(
        "nsight_agent.core.run_process",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, "cuda_api_sync[:args] -- CUDA sync\nOptions:\n", ""
        ),
    )
    assert "Options:" in svc._run(["analyze", "--help-rules", "cuda_api_sync"], tmp_path)
    with pytest.raises(NsightError):
        svc._run(["analyze", "--rule", "cuda_api_sync"], tmp_path)


@pytest.mark.parametrize("parameters", ["", "(rows=-1)", "(nvtx=Train:rows=-1)"])
def test_progress_line_and_missing_data_status(tmp_path, parameters):
    local = tmp_path / "中文 export.sqlite"
    prefix = f"Processing [{local}] with [/opt/nsight/rules/cuda_api_sync.py]{parameters}... \n"
    assert diagnostic_csv(prefix + table("cuda_api_sync"), local, "cuda_api_sync") == table(
        "cuda_api_sync"
    )
    with pytest.raises(NsightError) as error:
        diagnostic_csv(prefix + "SKIPPED: required CUDA tables missing\n", local, "cuda_api_sync")
    assert error.value.code == "MISSING_DATA"
    assert diagnostic_csv(prefix, local, "cuda_api_sync") == ""


def test_unknown_progress_is_not_silently_removed(tmp_path):
    local = tmp_path / "input.sqlite"
    output = "Processing [other.sqlite] with [/opt/rules/cuda_api_sync.py]... \n"
    assert diagnostic_csv(output, local, "cuda_api_sync") == output

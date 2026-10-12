"""Opt-in real Linux-report -> Windows Nsight -> MCP verification.

NSIGHT_INTEGRATION=1 python -m pytest -m integration -v
"""

import asyncio
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nsight_agent.analysis import CompareQuery, Scope
from nsight_agent.catalog import CATALOG, ReportOptions
from nsight_agent.core import NsightError, NsightService, NvtxTraceQuery, Query, StatsQuery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("NSIGHT_INTEGRATION") != "1",
        reason="Set NSIGHT_INTEGRATION=1 with Nsight installed",
    ),
]
SAMPLE = Path(__file__).resolve().parents[1] / "examples/reports/baseline_nvtx.nsys-rep"
SHA256 = "760052039bd392c997fdf2533a97292825121dfe818e18f1fd6b127e79ffedea"


@pytest.fixture(scope="module")
def capture(tmp_path_factory):
    assert SAMPLE.is_file(), "Download the documented public sample first."
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == SHA256
    cache = tmp_path_factory.mktemp("nsight")
    service = NsightService(cache_dir=cache)
    report_id = service.open_report(str(SAMPLE))["report_id"]
    yield service, report_id
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == SHA256


def direct_rows(result, cwd):
    """Independent CSV conversion; compares actual NVIDIA output, not a mock."""
    provenance = result["provenance"]
    process = subprocess.run(
        [provenance["executable"], *provenance["arguments"]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    assert not process.stderr.strip()
    return list(csv.DictReader(io.StringIO(process.stdout)))


@pytest.mark.parametrize(
    "kind", ["kernel_summary", "kernel_trace", "cuda_api_summary", "memory_time", "memory_size"]
)
def test_official_statistics_match(capture, tmp_path, kind):
    service, report_id = capture
    result = service.query(report_id, kind, Query(limit=200))
    raw = direct_rows(result, tmp_path)
    if kind == "kernel_trace":
        raw = [r for r in raw if r["GrdX"]]
    raw.sort(key=lambda r: float(r[result["sort_by"]]), reverse=True)
    assert result["total_rows"] == len(raw)
    for actual, expected in zip(result["rows"], raw[:200], strict=True):
        for column, value in actual.items():
            if isinstance(value, (int, float)):
                assert value == float(expected[column])
            else:
                assert value == (expected[column] or None)


@pytest.mark.parametrize("query", [Query(nvtx="Train"), Query(start_ns=0, end_ns=10_000_000_000)])
def test_range_filters_match(capture, tmp_path, query):
    service, report_id = capture
    result = service.query(report_id, "kernel_summary", query)
    raw = direct_rows(result, tmp_path)
    assert result["total_rows"] == len(raw) > 0
    assert result["rows"][0]["Total Time (ns)"] == int(raw[0]["Total Time (ns)"])


def test_sqlite_input_and_no_match(capture, tmp_path):
    service, report_id = capture
    baseline = service.query(report_id, "kernel_summary")
    sqlite = service.open_report(baseline["provenance"]["arguments"][-1])["report_id"]
    assert service.query(sqlite, "kernel_summary")["rows"] == baseline["rows"]
    assert (
        service.query(report_id, "kernel_summary", Query(name_contains="no-such-kernel"))["rows"]
        == []
    )


def test_real_stdio_workflow():
    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "nsight_agent"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                doctor = await session.call_tool("nsight_doctor", {})
                assert not doctor.isError and not doctor.structuredContent["missing_reports"]
                opened = await session.call_tool("nsight_open_report", {"path": str(SAMPLE)})
                assert not opened.isError
                report_id = opened.structuredContent["report_id"]
                for name in (
                    "nsight_kernel_summary",
                    "nsight_kernel_trace",
                    "nsight_cuda_api_summary",
                    "nsight_memory_summary",
                ):
                    result = await session.call_tool(
                        name, {"report_id": report_id, "query": {"limit": 2}}
                    )
                    assert not result.isError, result
                    assert result.structuredContent["rows"]
                filtered = await session.call_tool(
                    "nsight_kernel_summary",
                    {"report_id": report_id, "query": {"nvtx": "Train", "limit": 1}},
                )
                assert not filtered.isError and filtered.structuredContent["rows"]
                discovered = await session.call_tool(
                    "nsight_nvtx_summary", {"report_id": report_id}
                )
                assert not discovered.isError and discovered.structuredContent["rows"]
                trace = await session.call_tool(
                    "nsight_nvtx_trace",
                    {"report_id": report_id, "query": {"name_contains": "Train", "limit": 1}},
                )
                assert not trace.isError and trace.structuredContent["rows"][0]["time_query"]
                compared = await session.call_tool(
                    "nsight_compare",
                    {"baseline_report_id": report_id, "candidate_report_id": report_id},
                )
                assert not compared.isError
                assert all(
                    row["changes"]["Total Time (ns)"]["absolute"] == 0
                    for row in compared.structuredContent["rows"]
                )
                exported = await session.call_tool(
                    "nsight_export_analysis",
                    {"result_ids": [compared.structuredContent["result_id"]], "format": "json"},
                )
                assert not exported.isError
                assert Path(exported.structuredContent["path"]).is_file()

    asyncio.run(check())


@pytest.mark.parametrize("kind", ["nvtx_summary", "nvtx_trace"])
def test_nvtx_official_tables(capture, tmp_path, kind):
    service, report_id = capture
    result = service.query(report_id, kind)
    raw = direct_rows(result, tmp_path)
    raw.sort(key=lambda row: int(row[result["sort_by"]]), reverse=kind != "nvtx_trace")
    assert len(raw) == result["total_rows"]
    for row, expected in zip(result["rows"], raw[:20], strict=True):
        for column in result["columns"]:
            value = row[column]
            assert value == (
                float(expected[column])
                if isinstance(value, (int, float))
                else expected[column] or None
            )


def test_discovered_nvtx_time_query(capture, tmp_path):
    service, report_id = capture
    trace = service.query(report_id, "nvtx_trace", NvtxTraceQuery(name_contains="Train", limit=1))
    row = trace["rows"][0]
    assert row["time_query"] == {"start_ns": row["Start (ns)"], "end_ns": row["End (ns)"]}
    result = service.query(report_id, "kernel_summary", Query(**row["time_query"]))
    raw = direct_rows(result, tmp_path)
    assert result["rows"][0]["Total Time (ns)"] == int(raw[0]["Total Time (ns)"])


@pytest.fixture(scope="module")
def candidate(capture):
    service, _ = capture
    path = SAMPLE.with_name("firstOptimization.nsys-rep")
    expected = "d81a008bdccd386cd1a382b49f87e90ff5bbd729bd036a9bbe11d24fa1c06980"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    yield service.open_report(str(path))["report_id"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


@pytest.mark.parametrize(
    "kind", ["kernel_summary", "cuda_api_summary", "memory_time", "memory_size"]
)
def test_real_two_report_comparison(capture, candidate, tmp_path, kind):
    service, baseline = capture
    result = service.compare(
        baseline, candidate, kind, Scope(nvtx="Train"), Scope(nvtx="Train"), CompareQuery(limit=200)
    )
    name = "Operation" if kind.startswith("memory_") else "Name"
    left = {r[name]: r for r in direct_rows(result["baseline"], tmp_path)}
    right = {r[name]: r for r in direct_rows(result["candidate"], tmp_path)}
    assert result["total_rows"] == len(left.keys() | right.keys())
    assert len(result["rows"]) == result["total_rows"]
    for row in result["rows"]:
        b, c = left.get(row["name"]), right.get(row["name"])
        for metric, change in row["changes"].items():
            if b is None or c is None:
                assert change["absolute"] is None and change["reason"] == "missing_side"
            else:
                delta = float(c[metric]) - float(b[metric])
                assert change["absolute"] == pytest.approx(delta)
                if float(b[metric]):
                    assert change["relative_percent"] == pytest.approx(
                        delta / float(b[metric]) * 100
                    )
                else:
                    assert change["relative_percent"] is None
    exported = service.export_analysis([result["result_id"]], "json")
    assert json.loads(Path(exported["path"]).read_text(encoding="utf-8"))["results"][0] == result


@pytest.mark.parametrize("name", list(CATALOG))
def test_complete_catalog_against_official_cli(capture, tmp_path, name):
    service, report_id = capture
    if name == "nvtx_startend_sum":
        # This specific public capture has no Start/End NVTX events.
        with pytest.raises(NsightError) as error:
            service.stats(report_id, name)
        assert error.value.code == "MISSING_DATA"
        return
    result = service.stats(report_id, name, StatsQuery(limit=2))
    raw = direct_rows(result, tmp_path)
    sort = result["sort_by"]
    present = [r for r in raw if r[sort]]
    missing = [r for r in raw if not r[sort]]
    raw = (
        sorted(present, key=lambda r: float(r[sort]), reverse=result["filters"]["descending"])
        + missing
    )
    assert len(raw) == result["total_rows"]
    for actual, expected in zip(result["rows"], raw[:2], strict=True):
        for column in result["columns"]:
            value = actual[column]
            assert value == (
                float(expected[column])
                if isinstance(value, (int, float))
                else expected[column] or None
            )


@pytest.mark.parametrize(
    "name,options",
    [
        ("cuda_gpu_kern_sum", ReportOptions(name_format="base", annotate_nvtx=True)),
        ("cuda_kern_exec_trace", ReportOptions(name_format="mangled")),
        ("nvtx_kern_sum", ReportOptions(name_format="base")),
    ],
)
def test_actual_report_parameters(capture, tmp_path, name, options):
    service, report_id = capture
    result = service.stats(report_id, name, StatsQuery(nvtx="Train", limit=2), options)
    raw = direct_rows(result, tmp_path)
    assert result["total_rows"] == len(raw) > 0


def test_installer_checks_actual_connection(tmp_path, monkeypatch):
    from nsight_agent.configure import setup
    from nsight_agent.health import check_connection

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    result = setup()
    assert result["status"] == "ready"
    assert len(result["connection"]["tools"]) == 12
    assert len(result["connection"]["available_reports"]) == 18
    assert result["skill"]["status"] in ("installed", "unchanged")
    checked = check_connection(report=str(SAMPLE))
    assert checked["status"] == "connected"
    assert checked["sample"]["rows"][0]["Total Time (ns)"] == 1266481454


@pytest.mark.skipif(
    not os.environ.get("NSIGHT_STARTEND_REPORT"),
    reason="Optional locally generated Windows Start/End capture",
)
def test_real_startend_capture(tmp_path):
    service = NsightService(cache_dir=tmp_path)
    report_id = service.open_report(os.environ["NSIGHT_STARTEND_REPORT"])["report_id"]
    result = service.stats(report_id, "nvtx_startend_sum")
    raw = direct_rows(result, tmp_path)
    assert result["rows"][0]["Instances"] == int(raw[0]["Instances"]) == 3
    assert result["rows"][0]["Range"] == ":AsyncStep"

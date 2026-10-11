"""Opt-in real Linux-report -> Windows Nsight -> MCP verification.

NSIGHT_INTEGRATION=1 python -m pytest -m integration -v
"""

import asyncio
import csv
import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nsight_agent.core import NsightService, Query

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

    asyncio.run(check())

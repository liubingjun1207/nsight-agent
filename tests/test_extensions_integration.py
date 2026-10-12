"""Opt-in local capture, annotated eager operators and Compute imports on either OS."""

import asyncio
import csv
import io
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nsight_agent.compute import METRICS, ComputeQuery
from nsight_agent.core import NsightService, Query
from nsight_agent.health import TOOLS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("NSIGHT_INTEGRATION") != "1", reason="Opt-in real Nsight environment"
    ),
]


@pytest.mark.skipif(
    not os.environ.get("NSIGHT_CAPTURE_TARGET"), reason="Configured local test task required"
)
def test_real_local_capture(tmp_path):
    service = NsightService(cache_dir=tmp_path)
    target = os.environ["NSIGHT_CAPTURE_TARGET"]
    assert any(t["target_id"] == target for t in service.capture_targets()["targets"])
    result = service.capture(target)
    assert result["status"] == "captured" and Path(result["path"]).is_file()
    measured = service.query(result["report_id"], "kernel_summary")
    assert measured["rows"] and measured["rows"][0]["Instances"] > 0


@pytest.mark.skipif(
    not os.environ.get("NSIGHT_OPERATOR_REPORT"), reason="operator_workload.py capture required"
)
def test_real_recorded_eager_operator_association(tmp_path):
    service = NsightService(cache_dir=tmp_path)
    report_id = service.open_report(os.environ["NSIGHT_OPERATOR_REPORT"])["report_id"]
    result = service.operator_summary(report_id, Query(name_contains="aten::", limit=200))
    assert any("aten::mm" in row["NVTX Range"] for row in result["rows"])
    process = subprocess.run(
        [result["provenance"]["executable"], *result["provenance"]["arguments"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    official = [
        r for r in csv.DictReader(io.StringIO(process.stdout)) if "aten::" in r["NVTX Range"]
    ]
    assert len(official) == result["total_rows"]
    keys = ("NVTX Range", "Kernel Name", "PID", "TID")
    indexed = {tuple(r[k] for k in keys): r for r in official}
    for row in result["rows"]:
        expected = indexed[tuple(str(row[k]) for k in keys)]
        assert row["Total Time (ns)"] == int(expected["Total Time (ns)"])


@pytest.fixture(scope="module")
def compute(tmp_path_factory):
    if not os.environ.get("NSIGHT_COMPUTE_REPORT"):
        pytest.skip("Existing real .ncu-rep required")
    service = NsightService(cache_dir=tmp_path_factory.mktemp("compute"))
    report_id = service.compute_open_report(os.environ["NSIGHT_COMPUTE_REPORT"])["report_id"]
    return service, report_id


@pytest.mark.parametrize("group", list(METRICS))
def test_real_compute_metrics_match_official_import(compute, tmp_path, group):
    service, report_id = compute
    result = service.compute_metrics(report_id, group, ComputeQuery(limit=200))
    assert result["rows"]
    process = subprocess.run(
        [result["provenance"]["executable"], *result["provenance"]["arguments"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    raw = list(csv.reader(io.StringIO(process.stdout)))
    columns, units = raw[:2]
    official = {r[0]: dict(zip(columns, r, strict=True)) for r in raw[2:] if r}
    for row in result["rows"]:
        assert row["Raw Value"] == official[row["Kernel ID"]][row["Metric Name"]]
        assert row["Metric Unit"] == units[columns.index(row["Metric Name"])]
    exported = service.export_analysis([result["result_id"]], "json")
    assert json.loads(Path(exported["path"]).read_text(encoding="utf-8"))["results"][0] == result


@pytest.mark.skipif(
    not (os.environ.get("NSIGHT_CAPTURE_TARGET") and os.environ.get("NSIGHT_COMPUTE_REPORT")),
    reason="Configured local test task and real .ncu-rep required",
)
def test_real_extended_stdio_workflow(tmp_path):
    async def check():
        env = {k: v for k, v in os.environ.items() if k.startswith("NSIGHT_")}
        env["NSIGHT_CACHE_DIR"] = str(tmp_path)
        params = StdioServerParameters(command=sys.executable, args=["-m", "nsight_agent"], env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert {t.name for t in (await session.list_tools()).tools} == TOOLS

                async def call(tool, arguments):
                    result = await session.call_tool(
                        tool, arguments, read_timeout_seconds=timedelta(seconds=300)
                    )
                    assert not result.isError, result.content
                    return result.structuredContent

                targets = await call("nsight_capture_targets", {})
                assert targets["targets"]
                captured = await call(
                    "nsight_capture", {"target_id": os.environ["NSIGHT_CAPTURE_TARGET"]}
                )
                summary = await call("nsight_kernel_summary", {"report_id": captured["report_id"]})
                assert summary["rows"]
                await call("nsight_compute_doctor", {})
                opened = await call(
                    "nsight_compute_open_report", {"path": os.environ["NSIGHT_COMPUTE_REPORT"]}
                )
                result = await call(
                    "nsight_compute_metrics",
                    {"report_id": opened["report_id"], "group": "occupancy"},
                )
                assert result["rows"]
                exported = await call(
                    "nsight_export_analysis",
                    {"result_ids": [result["result_id"]], "format": "json"},
                )
                assert Path(exported["path"]).is_file()
                if operator_report := os.environ.get("NSIGHT_OPERATOR_REPORT"):
                    annotated = await call("nsight_open_report", {"path": operator_report})
                    operators = await call(
                        "nsight_operator_summary", {"report_id": annotated["report_id"]}
                    )
                    assert operators["rows"]

    asyncio.run(check())

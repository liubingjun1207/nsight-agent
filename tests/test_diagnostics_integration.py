"""Opt-in official analyze/STDIO checks on the licensed public Linux capture."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nsight_agent.core import NsightService, Query, parse_csv
from nsight_agent.diagnostics import RULES, DiagnosticOptions, diagnostic_csv
from nsight_agent.health import TOOLS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("NSIGHT_INTEGRATION") != "1", reason="Real Nsight opt-in"),
]
BASELINE = Path(__file__).resolve().parents[1] / "examples/reports/baseline_nvtx.nsys-rep"


@pytest.fixture(scope="module")
def diagnostic(tmp_path_factory):
    service = NsightService(cache_dir=tmp_path_factory.mktemp("diagnostic"))
    rid = service.open_report(str(BASELINE))["report_id"]
    return service, rid


@pytest.mark.parametrize("rule", list(RULES))
@pytest.mark.parametrize("scope", [{}, {"start_ns": 0, "end_ns": 1000000000}, {"nvtx": "Train"}])
def test_official_results_match_all_rules_and_scopes(diagnostic, tmp_path, rule, scope):
    service, rid = diagnostic
    result = service.analyze(rid, rule, Query(**scope, limit=200))
    process = subprocess.run(
        [result["provenance"]["executable"], *result["provenance"]["arguments"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    stdout = diagnostic_csv(process.stdout, Path(result["provenance"]["arguments"][-1]), rule)
    if stdout.strip():
        _, official = parse_csv(stdout, set(RULES[rule].columns), name_columns=("API Name", "Row#"))
    else:
        official = []
    assert result["official_findings"] == result["total_rows"] == len(official)
    expected = sorted(official, key=lambda r: r["Duration (ns)"], reverse=True)
    assert [{k: v for k, v in r.items() if k != "time_query"} for r in result["rows"]] == expected[
        :200
    ]
    assert result["status"] == ("findings" if official else "no_findings")


def test_gap_threshold_followup_and_pagination(diagnostic):
    service, rid = diagnostic
    result = service.analyze(rid, "gpu_gaps", Query(limit=1), DiagnosticOptions(gap_ms=1))
    assert result["total_rows"] == 954
    assert result["rows"][0]["Duration (ns)"] == 267528328
    assert result["next_offset"] == 1
    last = service.analyze(rid, "gpu_gaps", Query(offset=953), DiagnosticOptions(gap_ms=1))
    assert len(last["rows"]) == 1 and last["next_offset"] is None
    # Follow the measured diagnostic window with a supported official trace.
    followup = service.stats(
        rid, "cuda_api_trace", Query(**result["rows"][0]["time_query"], limit=2)
    )
    assert followup["rows"]
    assert service.analyze(rid, "gpu_time_util")["rows"][0]["In-Use (%)"] == 34.3


def test_real_missing_data_is_not_no_findings(tmp_path):
    import sqlite3

    source = tmp_path / "缺少 CUDA.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE StringIds (id INTEGER PRIMARY KEY, value TEXT)")
    svc = NsightService(cache_dir=tmp_path / "cache")
    rid = svc.open_report(str(source))["report_id"]
    from nsight_agent.core import NsightError

    with pytest.raises(NsightError) as error:
        svc.analyze(rid, "cuda_api_sync")
    assert error.value.code == "MISSING_DATA"


def test_real_diagnostic_stdio_export(tmp_path):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "nsight_agent"],
            env={**os.environ, "NSIGHT_CACHE_DIR": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert {t.name for t in (await session.list_tools()).tools} == TOOLS
                rules = await session.call_tool("nsight_analysis_rules", {})
                assert not rules.isError and len(rules.structuredContent["rules"]) == 6
                opened = await session.call_tool("nsight_open_report", {"path": str(BASELINE)})
                result = await session.call_tool(
                    "nsight_analyze",
                    {
                        "report_id": opened.structuredContent["report_id"],
                        "rule": "gpu_gaps",
                        "options": {"gap_ms": 1},
                        "query": {"limit": 2},
                    },
                )
                assert not result.isError and result.structuredContent["total_rows"] == 954
                export = await session.call_tool(
                    "nsight_export_analysis",
                    {
                        "result_ids": [result.structuredContent["result_id"]],
                        "format": "json",
                    },
                )
                assert not export.isError
                saved = json.loads(
                    Path(export.structuredContent["path"]).read_text(encoding="utf-8")
                )
                assert saved["results"][0] == result.structuredContent

    asyncio.run(check())

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "examples/evaluate_codex.py"
SPEC = importlib.util.spec_from_file_location("evaluate_codex", MODULE_PATH)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def call(tool, data=None, **extra):
    return {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "nsight",
            "tool": tool,
            "result": {"structuredContent": data} if data else {},
            **extra,
        },
    }


def test_evaluation_requires_actual_calls_not_model_claims():
    result = evaluation.inspect_events(
        [
            {"type": "turn.completed"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "All analysis passed"},
            },
        ],
        "core",
    )
    assert not result["passed"] and result["tool_calls"] == 0


def test_bottleneck_grader_requires_measured_scopes_and_followup():
    events = [call(tool) for tool in evaluation.CASES["bottlenecks"]["tools"]]
    for rule, count in {
        "cuda_api_sync": 1928,
        "cuda_memcpy_async": 1926,
        "cuda_memcpy_sync": 0,
        "cuda_memset_sync": 0,
        "gpu_gaps": 954,
        "gpu_time_util": 1,
    }.items():
        events.append(
            call(
                "nsight_analyze",
                {
                    "official_rule": rule,
                    "total_rows": count,
                    "filters": {},
                    "rule_parameters": {"gap": 1},
                    "rows": [],
                },
            )
        )
    events += [
        call("nsight_stats", {"official_report": "cuda_api_trace"}),
        {"type": "turn.completed"},
    ]
    result = evaluation.inspect_events(events, "bottlenecks")
    assert not result["passed"]
    assert "Train NVTX diagnostic absent." in result["errors"]
    assert "One-second diagnostic scope absent." in result["errors"]
    assert "No API trace followed an actual gap window." in result["errors"]


@pytest.mark.parametrize(
    "start,nvtx,expected",
    [
        (0, None, True),
        (999999999, None, False),
        (None, None, False),
        (0, "Train", False),
    ],
)
def test_first_second_requires_full_explicit_time_scope(tmp_path, start, nvtx, expected):
    records = []
    for rule, count in {
        "cuda_api_sync": 1928,
        "cuda_memcpy_async": 1926,
        "cuda_memcpy_sync": 0,
        "cuda_memset_sync": 0,
        "gpu_gaps": 954,
        "gpu_time_util": 1,
    }.items():
        records.append(
            {
                "official_rule": rule,
                "total_rows": count,
                "filters": {},
                "result_id": rule,
                "rule_parameters": {"gap": 1},
                "rows": [{"time_query": {"start_ns": 10, "end_ns": 20}}]
                if rule == "gpu_gaps"
                else [],
            }
        )
    records += [
        {"official_rule": "gpu_time_util", "filters": {"nvtx": "Train"}, "result_id": "train"},
        {
            "official_rule": "cuda_api_sync",
            "filters": {"start_ns": start, "end_ns": 1000000000, "nvtx": nvtx},
            "result_id": "first-second",
        },
        {
            "official_report": "cuda_api_trace",
            "filters": {"start_ns": 10, "end_ns": 20},
            "result_id": "trace",
        },
    ]
    export = tmp_path / "evidence.json"
    export.write_text(json.dumps({"results": records}), encoding="utf-8")
    events = [call(t) for t in evaluation.CASES["bottlenecks"]["tools"]]
    events += [
        call("nsight_analyze" if "official_rule" in r else "nsight_stats", r) for r in records
    ]
    events += [
        call("nsight_export_analysis", {"format": "json", "path": str(export)}),
        {"type": "turn.completed"},
    ]
    assert evaluation.inspect_events(events, "bottlenecks")["passed"] == expected


@pytest.mark.parametrize(
    "start,nvtx,expected",
    [
        (0, None, True),
        (9999999999, None, False),
        (None, None, False),
        (0, "Train", False),
    ],
)
def test_first_ten_seconds_requires_full_explicit_time_scope(start, nvtx, expected):
    events = [call(t) for t in evaluation.CASES["core"]["tools"]]
    events += [
        call("nsight_stats", {"official_report": r}) for r in evaluation.CASES["core"]["reports"]
    ]
    events += [
        call(
            "nsight_kernel_summary",
            {
                "official_report": "cuda_gpu_kern_sum",
                "filters": {},
                "rows": [{"Total Time (ns)": 1266481454, "Instances": 938}],
            },
        ),
        call(
            "nsight_kernel_summary",
            {
                "official_report": "cuda_gpu_kern_sum",
                "filters": {"start_ns": start, "end_ns": 10000000000, "nvtx": nvtx},
                "rows": [],
            },
        ),
        {"type": "turn.completed"},
    ]
    assert evaluation.inspect_events(events, "core")["passed"] == expected


def test_diagnostics_require_error_codes_and_true_empty_result():
    events = [call(tool) for tool in evaluation.CASES["diagnostics"]["tools"]]
    events += [
        call("nsight_open_report", error={"message": "[INVALID_REPORT]"}),
        call(
            "nsight_stats",
            arguments={"report": "nvtx_startend_sum"},
            error={"message": "[MISSING_DATA]"},
        ),
        call("nsight_kernel_summary", {"official_report": "cuda_gpu_kern_sum", "total_rows": 0}),
        {"type": "turn.completed"},
    ]
    assert evaluation.inspect_events(events, "diagnostics")["passed"]
    events.append({"type": "item.completed", "item": {"type": "command_execution"}})
    assert not evaluation.inspect_events(events, "diagnostics")["passed"]


def test_evidence_parser_accepts_both_sdk_result_encodings():
    assert evaluation.data_of({"result": {"structured_content": {"rows": []}}}) == {"rows": []}
    assert evaluation.data_of(
        {"result": {"content": [{"type": "text", "text": '{"rows":[]}'}]}}
    ) == {"rows": []}


def test_failed_status_not_masked_by_null_error():
    events = [call(tool) for tool in evaluation.CASES["launch"]["tools"]]
    events += [
        call("nsight_stats", {"official_report": report})
        for report in evaluation.CASES["launch"]["reports"]
    ]
    events += [{"type": "turn.completed"}, call("nsight_open_report", status="failed", error=None)]
    result = evaluation.inspect_events(events, "launch")
    assert not result["passed"] and "Unexpected failed tool call." in result["errors"]


def test_extensions_reject_preexisting_operator_evidence(tmp_path):
    exported = tmp_path / "evidence.json"
    exported.write_text("{}")
    events = [call(tool) for tool in evaluation.CASES["extensions"]["tools"]]
    events += [
        call("nsight_capture", {"status": "captured", "report_id": "new"}),
        call("nsight_kernel_summary", {"official_report": "cuda_gpu_kern_sum"}),
        call(
            "nsight_operator_summary",
            {
                "official_report": "nvtx_kern_sum",
                "association": "recorded_nvtx_launch_containment",
                "report_id": "old",
                "rows": [{}],
            },
        ),
        call("nsight_export_analysis", {"format": "json", "path": str(exported)}),
        {"type": "turn.completed"},
    ]
    events += [
        call(
            "nsight_compute_metrics",
            {"engine": "nsight_compute", "metric_group": group, "rows": [{"Metric Unit": "%"}]},
        )
        for group in ("occupancy", "throughput", "memory", "stalls", "launch")
    ]
    result = evaluation.inspect_events(events, "extensions")
    assert (
        not result["passed"]
        and "No recorded operator evidence from the newly captured task." in result["errors"]
    )

import importlib.util
from pathlib import Path

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

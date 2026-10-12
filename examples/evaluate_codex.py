"""Opt-in real Codex product evaluation. Reuses login; never copies auth to CI.

Run with the installed release Python. Raw events stay in the chosen local output directory.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from nsight_agent.core import discover_nsys, run_process

CASES = {
    "core": {
        "question": "分析 baseline 报告：列出累计耗时最高的十个 CUDA kernel；查看第一名最早的两次执行；发现 NVTX 范围并查看 Train 的一次明细；再查报告前十秒的 kernel 汇总。另查 kernel 的 grid/block 分组、CPU 同步 API 汇总与两次明细、内存操作耗时与字节数，以及两条 GPU memcpy 执行明细。每项最多十行，说明各自时间含义。",
        "tools": {
            "nsight_capabilities",
            "nsight_open_report",
            "nsight_kernel_summary",
            "nsight_kernel_trace",
            "nsight_nvtx_summary",
            "nsight_nvtx_trace",
            "nsight_cuda_api_summary",
            "nsight_memory_summary",
            "nsight_stats",
        },
        "reports": {"cuda_gpu_kern_gb_sum", "cuda_api_trace", "cuda_gpu_trace"},
    },
    "launch": {
        "question": "分析 baseline：展示 kernel 发射、排队和执行时间的汇总与两条单次明细；展示 Train 的 GPU 投影汇总和一次投影明细；再按 NVTX 归属列出 kernel 分组；给出区分 CPU API 与 GPU 事件的联合汇总。每项最多两行，解释排队空值、嵌套归属和投影的限制。",
        "tools": {"nsight_capabilities", "nsight_open_report", "nsight_stats"},
        "reports": {
            "cuda_kern_exec_sum",
            "cuda_kern_exec_trace",
            "nvtx_gpu_proj_sum",
            "nvtx_gpu_proj_trace",
            "nvtx_kern_sum",
            "cuda_api_gpu_sum",
        },
    },
    "compare": {
        "question": "分别打开 baseline 和 candidate，按两份报告各自的 Train NVTX 范围比较 kernel、CPU CUDA API、内存耗时与字节数，每类显示两行并说明次数变化。把四类对比证据导出成 Markdown 和 JSON，返回文件路径；不能根据累计时间差直接声称应用整体加速。",
        "tools": {
            "nsight_capabilities",
            "nsight_open_report",
            "nsight_compare",
            "nsight_export_analysis",
        },
        "reports": set(),
    },
    "diagnostics": {
        "question": "先尝试打开 missing_report 路径并说明错误；然后打开 baseline，查询 Start/End NVTX 汇总（样例可能没有该事件）与名称包含 NO_SUCH_KERNEL_42 的 kernel 汇总，区别缺少数据和无匹配。最后说明这个服务能否分析 Nsight Compute 的 SM occupancy。不要把未知或缺失数据写成零。",
        "tools": {
            "nsight_capabilities",
            "nsight_open_report",
            "nsight_stats",
            "nsight_kernel_summary",
        },
        "reports": {"nvtx_startend_sum"},
    },
}


def data_of(item):
    result = item.get("result") or {}
    if not isinstance(result, dict):
        return None
    data = result.get("structuredContent") or result.get("structured_content")
    if data:
        return data
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                data = json.loads(block["text"])
                if isinstance(data, dict):
                    return data
            except (ValueError, KeyError):
                pass
    return None


def inspect_events(events, case):
    items = [e["item"] for e in events if e.get("type") == "item.completed"]
    calls = [i for i in items if i.get("type") == "mcp_tool_call"]
    tools = {i.get("tool") for i in calls if i.get("server") == "nsight"}
    records = [data_of(i) for i in calls]
    records = [r for r in records if r]
    reports = {r.get("official_report") for r in records}
    errors = []
    if missing := CASES[case]["tools"] - tools:
        errors.append("Missing actual tool calls: " + str(sorted(missing)))
    if missing := CASES[case]["reports"] - reports:
        # A required missing-data report still has to have been attempted.
        attempted = {
            i.get("arguments", {}).get("report")
            for i in calls
            if isinstance(i.get("arguments"), dict)
        }
        if case != "diagnostics" or missing - attempted:
            errors.append("Missing reports: " + str(sorted(missing)))
    if any(i.get("type") in ("command_execution", "file_change", "web_search") for i in items):
        errors.append("Used a fallback outside the Nsight tool workflow.")
    if any(i.get("server") != "nsight" for i in calls):
        errors.append("Used a different MCP server.")
    if not any(e.get("type") == "turn.completed" for e in events):
        errors.append("Codex turn did not complete.")
    if case == "core":
        summaries = [
            r
            for r in records
            if r.get("official_report") == "cuda_gpu_kern_sum"
            and not r["filters"].get("nvtx")
            and r["filters"].get("start_ns") is None
            and r["filters"].get("end_ns") is None
        ]
        if not any(
            r["rows"]
            and r["rows"][0]["Total Time (ns)"] == 1266481454
            and r["rows"][0]["Instances"] == 938
            for r in summaries
        ):
            errors.append("Whole-report top-kernel evidence missing or incorrect.")
        if not any(
            r.get("official_report") == "cuda_gpu_kern_sum"
            and r["filters"].get("end_ns") == 10000000000
            for r in records
        ):
            errors.append("Did not apply the requested ten-second boundary.")
    if case == "compare":
        comparisons = [r for r in records if "baseline" in r and "candidate" in r]
        if {r.get("kind") for r in comparisons} != {
            "kernel_summary",
            "cuda_api_summary",
            "memory_time",
            "memory_size",
        }:
            errors.append("Four comparison kinds not observed.")
        if not all(
            r[side]["filters"].get("nvtx") == "Train"
            for r in comparisons
            for side in ("baseline", "candidate")
        ):
            errors.append("Did not use independent Train scopes on both reports.")
        paths = [r["path"] for r in records if "path" in r and "format" in r]
        if not {Path(p).suffix for p in paths} >= {".md", ".json"} or not all(
            Path(p).is_file() for p in paths
        ):
            errors.append("Both real export files were not created.")
    if case == "diagnostics":
        text = json.dumps(calls, ensure_ascii=False)
        if "INVALID_REPORT" not in text or "MISSING_DATA" not in text:
            errors.append("Expected diagnostic error codes absent.")
        if not any(
            r.get("official_report") == "cuda_gpu_kern_sum" and r["total_rows"] == 0
            for r in records
        ):
            errors.append("No-match response absent.")
    elif any(
        i.get("status") == "failed" or i.get("error") or (i.get("result") or {}).get("isError")
        for i in calls
    ):
        errors.append("Unexpected failed tool call.")
    if case == "diagnostics":
        for item in calls:
            if item.get("status") == "failed":
                text = json.dumps(item, ensure_ascii=False)
                if not (
                    (item.get("tool") == "nsight_open_report" and "INVALID_REPORT" in text)
                    or (item.get("tool") == "nsight_stats" and "MISSING_DATA" in text)
                ):
                    errors.append("Unexpected diagnostic failure.")
    return {
        "passed": not errors,
        "errors": errors,
        "tool_calls": len(calls),
        "tools": sorted(tools),
        "reports": sorted(r for r in reports if r),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if args.repetitions < 1 or args.timeout < 1:
        parser.error("Positive repetitions/timeout required.")
    codex = shutil.which("codex")
    if not codex:
        parser.error("Install Codex CLI and sign in first.")
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    model = (
        tomllib.loads(config.read_text(encoding="utf-8")).get("model") if config.exists() else None
    )
    nsys = str(discover_nsys())
    server = (
        "{command="
        + json.dumps(sys.executable)
        + ',args=["-m","nsight_agent"],enabled=true,required=true,startup_timeout_sec=30,tool_timeout_sec=600,default_tools_approval_mode="approve",env={NSIGHT_NSYS_PATH='
        + json.dumps(nsys)
        + ',PYTHONIOENCODING="utf-8"}}'
    )
    common = [
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-c",
        "mcp_servers.nsight=" + server,
    ]
    if model:
        common += ["-c", "model=" + json.dumps(model)]
    baseline = (args.reports_dir / "baseline_nvtx.nsys-rep").resolve()
    candidate = (args.reports_dir / "firstOptimization.nsys-rep").resolve()
    header = f"这是 Nsight Agent 的产品验证。只使用 nsight MCP 工具进行分析，不执行 shell、SQL、网页或编辑代码。先发现可调用能力；只查询本次问题要求的报告，不要输出整份原始报告。baseline={baseline}\n"
    results = []
    for case in args.case or list(CASES):
        for repetition in range(1, args.repetitions + 1):
            context = ""
            if case == "compare":
                context = f"candidate={candidate}\n"
            elif case == "diagnostics":
                context = f"missing_report={args.output_dir / 'does-not-exist.nsys-rep'}\n"
            log = args.output_dir / f"{case}-{repetition}.jsonl"
            answer = args.output_dir / f"{case}-{repetition}-answer.md"
            stderr = args.output_dir / f"{case}-{repetition}-stderr.txt"
            try:
                process = run_process(
                    common + ["-o", str(answer), "-"],
                    input_text=header + context + CASES[case]["question"],
                    env=os.environ.copy(),
                    timeout=args.timeout,
                    cwd=args.output_dir.resolve(),
                )
                exit_code = process.returncode
                log.write_text(process.stdout, encoding="utf-8")
                stderr.write_text(process.stderr, encoding="utf-8")
            except subprocess.TimeoutExpired:
                exit_code = -1
                log.write_text("", encoding="utf-8")
                stderr.write_text(
                    "Codex evaluation timed out; owned process tree terminated.", encoding="utf-8"
                )
            events = []
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            result = inspect_events(events, case)
            if exit_code:
                result["passed"] = False
                result["errors"].append(f"Codex exit {exit_code}; inspect local stderr/log.")
            result.update(case=case, repetition=repetition, exit_code=exit_code)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "model": model or "CLI default",
        "python": sys.version.split()[0],
        "codex_version": subprocess.check_output([codex, "--version"], text=True).strip(),
        "results": results,
        "note": "Actual tool evidence, not a guarantee for all prompts. Final interpretation requires review of local answers. Raw logs and authentication are not included in this summary.",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()

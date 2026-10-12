# v1.1: local collection, Linux and optional Compute

The twelve existing tools remain compatible. Six tools add local Systems collection, recorded PyTorch eager NVTX associations and optional Compute report imports. The Systems statistics catalog remains fixed at 18 reports. See [the detailed Chinese guide](EXTENSIONS.zh-CN.md) and [validation evidence](VALIDATION-v1.1.md).

## Linux installation

Run the MCP server and Codex CLI/IDE environment on the host that owns the workload/reports. Install Python 3.11+ and Nsight Systems; set `NSIGHT_NSYS_PATH` if `nsys` is not on PATH.

```bash
export NSIGHT_NSYS_PATH=/absolute/nsight/target-linux-x64/nsys
export NSIGHT_CACHE_DIR="$HOME/.cache/nsight-agent"
bash install.sh
```

Or create a virtual environment, install the package and run its `--setup` and `--check-connection` commands using `.venv/bin/python`. Reconnect Codex and verify 18 tools. Configuration uses `~/.codex/config.toml` or `CODEX_HOME`. [Official MCP configuration](https://developers.openai.com/codex/mcp)

Local collection and analysis need no Windows file transfer. This release adds no SSH, remote transport, job scheduling or cluster management.

## Register a collection task

Collection is disabled until the owner creates a local TOML registry:

```toml
[targets.operator-example]
description = "Three annotated PyTorch eager steps"
command = ["/absolute/project/.venv/bin/python", "/absolute/project/examples/operator_workload.py"]
cwd = "/absolute/project"
duration_seconds = 30
timeout_seconds = 120
```

Use absolute executable/cwd paths; the configured Python needs CUDA-enabled PyTorch for this example. On Windows use appropriate absolute Python/script paths. `examples/driver_workload.py` is a real, verified 20-launch CUDA workload requiring no PyTorch, but deliberately has no operator NVTX labels.

```bash
export NSIGHT_CAPTURE_CONFIG=/absolute/project/capture-targets.toml
.venv/bin/python -m nsight_agent --setup
```

Setup passes the registry path to the STDIO child and preserves optional feature environment settings on upgrades. After reconnecting, ask Codex to list tasks with `nsight_capture_targets`, run `nsight_capture(target_id="operator-example")`, and analyze its returned report_id.

Only the preconfigured task can run; tool calls accept no executable or extra arguments. CUDA/NVTX tracing is fixed, CPU sampling/context switches are disabled, and outputs use unique managed directories. Duration is 1–120s; command timeout is 30–300s and at least duration+15s. The duration limit can terminate the application and timeout cleanup targets its owned process tree. Configured applications may write their own files or consume GPU resources. Register bounded, repeatable tasks and collect only when requested. [Official Systems guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)

## Recorded eager operator associations

`operator_workload.py` uses `torch.autograd.profiler.emit_nvtx(record_shapes=True)`. `nsight_operator_summary` queries official `nvtx_kern_sum`, defaulting to a `name_contains="aten::"` filter. It preserves actual labels and launch-containment evidence. [PyTorch documentation](https://docs.pytorch.org/docs/main/autograd.html#torch.autograd.profiler.emit_nvtx)

Rows are range/kernel associations, not unique operator totals; nested ranges can duplicate kernels. Unannotated reports cannot reliably recover aten identities from kernel names. Full `torch.compile`/fusion attribution and automatic training-code instrumentation are excluded.

## Optional Compute imports

Install Nsight Compute and set `NSIGHT_NCU_PATH` if needed, then rerun setup. Missing Compute does not disable Systems. Read an existing local `.ncu-rep` using `nsight_compute_doctor`, `nsight_compute_open_report`, then `nsight_compute_metrics`.

Fixed groups are `occupancy`, `throughput`, `memory`, `stalls`, and `launch`; their exact metric allowlists live in `src/nsight_agent/compute.py`. Query accepts `name_contains`, report-local `kernel_id`, `offset`, and `limit` (1–200). Pagination counts flattened kernel/metric rows. Values retain official units, exact names and raw CSV values. Absent metrics are listed in `missing_metrics`; unavailable values are null, not zero.

```json
{"report_id":"ncu-report-id","group":"occupancy","query":{"kernel_id":"0","limit":20}}
```

Imports disable user config, select the raw CSV page, use fixed official CLI arguments and preserve original reports. Result IDs work with `nsight_export_analysis`. No arbitrary metric/section/rule-script interface, ncu collection or automatic cross-capture matching is provided. Additional counters require separate target-GPU collection; Compute replay can affect timing. Occupancy alone is not an optimization verdict, and stall ratio/percentage variants have distinct denominators. [Compute profiling guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)
